"""Interview API routes — wired to Prep / Live / Post agents.

Supports two modes:
  - Text mode:  REST endpoints for text-based mock interviews
  - Voice mode: WebSocket + audio endpoints for real voice interviews
"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from datetime import datetime

from app.agent.prep.agent import PrepAgent
from app.agent.live.agent import LiveAgent
from app.agent.post.agent import PostAgent
from app.models.interview import (
    InterviewContext,
    InterviewStatus,
    PhaseEnum,
    RoleEnum,
    Turn,
)
from app.services.livekit.worker import VoiceInterviewWorker
from app.services.resume_parser import parse_resume
from app.services.voice.audio_utils import pcm_to_wav

router = APIRouter()

# ── Agent singletons ─────────────────────────────────────
_prep_agent = PrepAgent()
_live_agent = LiveAgent()
_post_agent = PostAgent()

# ── In-memory store (MVP — will move to Redis later) ────
_sessions: dict[str, InterviewContext] = {}
_workers: dict[str, VoiceInterviewWorker] = {}

# Session TTL: auto-cleanup sessions older than 2 hours
_SESSION_TTL_SECONDS = 7200

import time
_last_cleanup = time.time()


def cleanup_expired_sessions():
    """Public cleanup function called by middleware."""
    _cleanup_expired_sessions()


def _cleanup_expired_sessions():
    """Remove sessions older than TTL. Called before each request."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 300:  # Run at most every 5 min
        return
    _last_cleanup = now
    expired = [
        sid for sid, ctx in _sessions.items()
        if (now - ctx.created_at.timestamp()) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _sessions.pop(sid, None)
        _workers.pop(sid, None)


@router.post("/create", response_model=InterviewContext)
async def create_interview(
    position: str = Form(""),
    resume: UploadFile | None = File(None),
):
    """Create a new interview session. Upload a resume (PDF/DOCX/TXT) for personalised questions.

    position is optional — when a resume is provided, the LLM infers the target role.
    """
    import logging
    _log = logging.getLogger(__name__)

    resume_text: str | None = None
    resume_data: dict | None = None  # Structured resume output (v2)

    if resume and resume.filename:
        content = await resume.read()
        _log.info(f"Received resume: filename={resume.filename!r}, size={len(content)} bytes, content_type={resume.content_type!r}")
        try:
            resume_data = await parse_resume(content, resume.filename)
            resume_text = resume_data["text"]
            _log.info(
                f"Parsed resume: {resume_data['metadata']['char_count']} chars, "
                f"{resume_data['metadata']['paragraph_count']} paragraphs, "
                f"{resume_data['metadata']['table_count']} tables, "
                f"{len(resume_data['blocks'])} blocks (ordered), "
                f"quality={'OK' if not resume_data['quality']['suspicious'] else 'SUSPICIOUS: ' + str(resume_data['quality']['issues'])}"
            )
            if resume_data["text_truncated"]:
                _log.warning(f"Resume text truncated from {resume_data['metadata']['char_count']} to {len(resume_text)} chars")
        except ValueError as e:
            _log.warning(f"Resume parse ValueError: {e}")
            raise HTTPException(400, f"简历解析失败: {e}")
        except ImportError as e:
            _log.error(f"Resume parse ImportError: {e}")
            raise HTTPException(500, f"缺少依赖: {e}")
        except Exception as e:
            _log.error(f"Resume parse unexpected error: {type(e).__name__}: {e}")
            raise HTTPException(400, f"简历解析异常: {e}")
    else:
        _log.warning(f"No resume received: resume={resume is not None}, filename={resume.filename if resume else 'N/A'}")

    if not resume_text:
        raise HTTPException(400, "请上传简历文件（PDF/DOCX/TXT），AI 将根据你的背景生成个性化面试")

    position = position or ""  # Empty string if not provided
    ctx = await _prep_agent.run(position=position, resume_text=resume_text)
    _sessions[ctx.session_id] = ctx
    return ctx


@router.get("/{session_id}", response_model=InterviewContext)
async def get_interview(session_id: str) -> InterviewContext:
    """Get current interview state."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    return _sessions[session_id]


@router.post("/{session_id}/start", response_model=InterviewContext)
async def start_interview(session_id: str) -> InterviewContext:
    """Transition to Live and return the first interviewer message.

    In adaptive mode, the first question is a personalised opening
    generated from the candidate's resume/profile.
    """
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]

    # Run Live agent's on_start (now initializes adaptive state)
    first_turn = await _live_agent.on_start(ctx)
    ctx.transcript.append(first_turn)

    # In adaptive mode, total_questions is estimated (not fixed)
    if ctx.adaptive_mode and ctx.adaptive_state:
        # Estimate based on skills × avg questions per skill
        estimated = len(ctx.adaptive_state.skills) * 3
        ctx.total_questions = estimated

    return ctx


@router.post("/{session_id}/send", response_model=InterviewContext)
async def send_message(session_id: str, content: str) -> InterviewContext:
    """Candidate sends a message during Live phase."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    if ctx.status != InterviewStatus.LIVE:
        raise HTTPException(400, "Interview is not live")

    # 1. Record candidate turn
    ctx.transcript.append(Turn(
        role=RoleEnum.CANDIDATE,
        content=content,
        phase=ctx.current_phase,
    ))

    # 2. Run Live agent → generate interviewer response
    response_turn = await _live_agent.on_candidate_message(ctx, content)

    # Check if interview was completed
    if "面试到这里就结束了" in response_turn.content or "感谢你的时间" in response_turn.content:
        ctx.status = InterviewStatus.POST

    ctx.transcript.append(response_turn)

    return ctx


@router.post("/{session_id}/pause")
async def pause_interview(session_id: str):
    """Pause the interview. State is preserved for later resume."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    try:
        _live_agent.pause(ctx)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"status": "paused", "elapsed_seconds": ctx.elapsed_seconds}


@router.post("/{session_id}/resume", response_model=InterviewContext)
async def resume_interview(session_id: str) -> InterviewContext:
    """Resume a paused interview. Returns the context with a system resume message."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    try:
        resume_turn = _live_agent.resume(ctx)
    except ValueError as e:
        raise HTTPException(400, str(e))

    ctx.transcript.append(resume_turn)
    return ctx


@router.get("/{session_id}/progress")
async def get_progress(session_id: str):
    """Get interview progress: phase, questions done/remaining, elapsed time, skills."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    return _live_agent.get_progress(ctx)


@router.get("/{session_id}/skills")
async def get_skills(session_id: str):
    """Get adaptive skill estimates — score, confidence, and coverage for each skill."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    if not ctx.adaptive_state:
        return {"skills": {}, "coverage_pct": 0, "current_topic": ""}

    skills_data = {}
    for name, skill in ctx.adaptive_state.skills.items():
        skills_data[name] = {
            "score": skill.score,
            "confidence": round(skill.confidence, 2),
            "evidence_count": skill.evidence_count,
            "importance": skill.importance,
            "coverage": round(ctx.adaptive_state.coverage.get(name, 0.0), 2),
        }

    total_cov = sum(ctx.adaptive_state.coverage.values())
    skill_count = len(ctx.adaptive_state.coverage)
    coverage_pct = round((total_cov / skill_count) * 100) if skill_count > 0 else 0

    return {
        "skills": skills_data,
        "coverage_pct": coverage_pct,
        "current_topic": ctx.adaptive_state.current_topic,
        "current_difficulty": ctx.adaptive_state.current_difficulty,
        "turns_on_topic": ctx.adaptive_state.turns_on_topic,
        "phase": ctx.current_phase.value,
    }


@router.post("/{session_id}/finish", response_model=InterviewContext)
async def finish_interview(session_id: str) -> InterviewContext:
    """End the interview → run Post scoring agent."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]

    # Run Post agent
    ctx = await _post_agent.run(ctx)
    ctx.completed_at = datetime.now()  # B3 fix: use actual completion time

    return ctx


# ═══════════════════════════════════════════════════════════
# Voice-mode endpoints
# ═══════════════════════════════════════════════════════════

@router.post("/{session_id}/voice/start")
async def voice_start(session_id: str):
    """Start voice mode for a prepared session.
    Returns the interviewer's opening TTS audio (base64).
    """
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]
    worker = VoiceInterviewWorker(ctx)
    _workers[session_id] = worker

    audio = await worker.start()
    import base64
    # B5 fix: wrap PCM in WAV header for browser playback
    wav_audio = pcm_to_wav(audio) if audio else b""
    return {
        "session_id": session_id,
        "audio_base64": base64.b64encode(wav_audio).decode("utf-8") if wav_audio else "",
        "text": ctx.transcript[-1].content if ctx.transcript else "",
        "phase": ctx.current_phase.value,
    }


@router.post("/{session_id}/voice/send")
async def voice_send(session_id: str, text: str):
    """Send a text message in voice mode (fallback for when STT isn't ready).
    Returns interviewer's reply text + TTS audio (base64).
    """
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    worker = _workers.get(session_id)
    if not worker:
        worker = VoiceInterviewWorker(_sessions[session_id])
        _workers[session_id] = worker

    reply_text = await worker.handle_text(text)
    audio = await worker.tts.synthesise(reply_text)

    import base64
    # B5 fix: wrap PCM in WAV header
    wav_audio = pcm_to_wav(audio) if audio else b""
    return {
        "text": reply_text,
        "audio_base64": base64.b64encode(wav_audio).decode("utf-8") if wav_audio else "",
        "phase": _sessions[session_id].current_phase.value,
        "is_done": worker.is_done(),
    }


@router.websocket("/{session_id}/voice/ws")
async def voice_websocket(ws: WebSocket, session_id: str):
    """WebSocket endpoint for real-time voice interview.

    Client sends: binary audio frames (PCM 16kHz 16-bit mono)
    Server sends: JSON messages with {type, text, audio_base64, phase}
    """
    await ws.accept()

    if session_id not in _sessions:
        await ws.send_json({"type": "error", "message": "Session not found"})
        await ws.close()
        return

    ctx = _sessions[session_id]
    worker = VoiceInterviewWorker(ctx)
    _workers[session_id] = worker

    # Send opening message
    opening_audio = await worker.start()
    import base64
    # B5 fix: wrap PCM in WAV header
    opening_wav = pcm_to_wav(opening_audio) if opening_audio else b""
    await ws.send_json({
        "type": "interviewer",
        "text": ctx.transcript[-1].content if ctx.transcript else "",
        "audio_base64": base64.b64encode(opening_wav).decode("utf-8") if opening_wav else "",
        "phase": ctx.current_phase.value,
        "is_done": False,
    })

    try:
        while True:
            data = await ws.receive()

            if "bytes" in data:
                # Binary audio frame → STT → Agent → TTS
                audio_data = data["bytes"]
                response_audio = await worker.handle_audio(audio_data)

                # B5 fix: wrap PCM in WAV header
                response_wav = pcm_to_wav(response_audio) if response_audio else b""
                await ws.send_json({
                    "type": "interviewer",
                    "text": ctx.transcript[-1].content if ctx.transcript else "",
                    "audio_base64": base64.b64encode(response_wav).decode("utf-8") if response_wav else "",
                    "phase": ctx.current_phase.value,
                    "is_done": worker.is_done(),
                })

            elif "text" in data:
                # Text message fallback
                text = data["text"]
                reply = await worker.handle_text(text)

                await ws.send_json({
                    "type": "interviewer",
                    "text": reply,
                    "audio_base64": "",
                    "phase": ctx.current_phase.value,
                    "is_done": worker.is_done(),
                })

            if worker.is_done():
                await ws.send_json({"type": "done", "message": "Interview completed"})
                break

    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})
    finally:
        if not ctx.transcript:
            pass  # No transcript to save
        try:
            await ws.close()
        except Exception:
            pass
