"""Voice service interfaces (Provider-Adapter pattern).

Every external voice provider sits behind a narrow Protocol.
The default wiring is Mock-first — runs with zero API keys.
Swap in real providers by changing one env var.
"""

from __future__ import annotations

from typing import Protocol


class SpeechToText(Protocol):
    """Convert audio bytes → text string."""

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        ...


class TextToSpeech(Protocol):
    """Convert text string → audio bytes."""

    async def synthesise(self, text: str) -> bytes:
        ...
