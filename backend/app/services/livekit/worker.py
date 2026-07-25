"""LiveKit Agent worker — wires STT → LangGraph Agent → TTS.

This is the entry point for the voice interview experience.
It uses the Provider-Adapter pattern: STT/TTS are injected,
so Mock providers work without any API keys.

The "LLM" in the voice pipeline is actually our LiveAgent
(running the LangGraph interview state machine).

Architecture:
  User audio → [STT] → text → [LiveAgent.on_candidate_message()] → text → [TTS] → audio

In M2, we keep the same InterviewContext flow:
  1. PrepAgent runs before the call (via REST API)
  2. LiveKit Worker handles the real-time voice loop
  3. PostAgent runs after the call (via REST API)
"""

from __future__ import annotations

import asyncio
import logging

from app.agent.live.agent import LiveAgent
from app.models.interview import InterviewContext, RoleEnum, Turn
from app.services.voice.factory import create_stt, create_tts

logger = logging.getLogger(__name__)


class VoiceInterviewWorker:
    """Manages a voice-based interview session.

    In production, this would be hooked into LiveKit's AgentSession.
    For M2 MVP, we provide a simpler WebSocket-based voice loop
    that can be upgraded to full LiveKit integration.
    """

    def __init__(self, ctx: InterviewContext):
        self.ctx = ctx
        self.stt = create_stt()
        self.tts = create_tts()
        self.live_agent = LiveAgent()

    # ── Public API ───────────────────────────────────────

    async def start(self) -> bytes:
        """Return the opening interviewer message as TTS audio."""
        turn = await self.live_agent.on_start(self.ctx)
        self.ctx.transcript.append(turn)
        return await self.tts.synthesise(turn.content)

    async def handle_audio(self, audio_data: bytes, sample_rate: int = 16000) -> bytes:
        """Process a candidate's audio response.

        1. STT → text
        2. LiveAgent → interviewer reply text
        3. TTS → audio response

        Returns the interviewer's audio response.
        """
        # 1. Speech → Text
        text = await self.stt.transcribe(audio_data, sample_rate)
        if not text or text == "[mock-transcription]":
            logger.warning("STT returned empty or mock result")
            return b""

        # Record candidate turn
        self.ctx.transcript.append(Turn(
            role=RoleEnum.CANDIDATE,
            content=text,
            phase=self.ctx.current_phase,
        ))

        # 2. Text → Agent → Reply text
        reply_turn = await self.live_agent.on_candidate_message(self.ctx, text)
        self.ctx.transcript.append(reply_turn)

        # 3. Reply text → Audio
        audio = await self.tts.synthesise(reply_turn.content)
        return audio

    async def handle_text(self, text: str) -> str:
        """Handle a text-based candidate response (fallback mode).

        Returns the interviewer's text reply.
        """
        self.ctx.transcript.append(Turn(
            role=RoleEnum.CANDIDATE,
            content=text,
            phase=self.ctx.current_phase,
        ))
        reply_turn = await self.live_agent.on_candidate_message(self.ctx, text)
        self.ctx.transcript.append(reply_turn)
        return reply_turn.content

    def is_done(self) -> bool:
        """Check if the interview has completed."""
        return self.ctx.status == "post"
