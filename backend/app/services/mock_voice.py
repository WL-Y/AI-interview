"""Mock STT / TTS services for offline development.

In Mock mode:
- STT: returns the text passed to it (text-in, text-out)
- TTS: no-ops, just logs what it would have spoken
"""

from app.models.interview import Turn, RoleEnum


class MockSTT:
    """Fake speech-to-text that takes a text string and returns it as-is."""

    async def transcribe(self, audio_data: bytes) -> str:
        # In mock mode, audio_data is ignored.
        # In real mode, this would call Volcano Engine STT.
        return "[mock-transcription]"


class MockTTS:
    """Fake text-to-speech that logs the text instead of synthesising."""

    async def synthesise(self, text: str) -> bytes:
        # In mock mode, return empty bytes (audio won't be played).
        # In real mode, this would call Volcano Engine TTS.
        return b""
