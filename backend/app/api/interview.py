"""Interview API routes — wired to Prep / Live / Post agents.

Supports two modes:
  - Text mode:  REST endpoints for text-based mock interviews
  - Voice mode: WebSocket + audio endpoints for real voice interviews
"""

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

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
    position: str = "前端工程师",
    resume: UploadFile | None = File(None),
):
    """Create a new interview session. Optionally upload a resume (PDF/DOCX/TXT)."""
    resume_text: str | None = None

    if resume and resume.filename:
        content = await resume.read()
        try:
            resume_text = await parse_resume(content, resume.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except ImportError as e:
            raise HTTPException(500, str(e))

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
    """Transition to Live and return the first interviewer message."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]

    # Run Live agent's on_start
    first_turn = await _live_agent.on_start(ctx)
    ctx.transcript.append(first_turn)

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


@router.post("/{session_id}/finish", response_model=InterviewContext)
async def finish_interview(session_id: str) -> InterviewContext:
    """End the interview → run Post scoring agent."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")

    ctx = _sessions[session_id]

    # Run Post agent
    ctx = await _post_agent.run(ctx)
    ctx.completed_at = ctx.completed_at or ctx.created_at

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
    return {
        "session_id": session_id,
        "audio_base64": base64.b64encode(audio).decode("utf-8") if audio else "",
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
    return {
        "text": reply_text,
        "audio_base64": base64.b64encode(audio).decode("utf-8") if audio else "",
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
    await ws.send_json({
        "type": "interviewer",
        "text": ctx.transcript[-1].content if ctx.transcript else "",
        "audio_base64": base64.b64encode(opening_audio).decode("utf-8") if opening_audio else "",
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

                await ws.send_json({
                    "type": "interviewer",
                    "text": ctx.transcript[-1].content if ctx.transcript else "",
                    "audio_base64": base64.b64encode(response_audio).decode("utf-8") if response_audio else "",
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
