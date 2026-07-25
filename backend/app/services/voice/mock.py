"""Mock voice providers for offline development.

- MockSTT: ignores audio, returns a canned string.
- MockTTS: logs text, returns empty bytes.
"""


class MockSTT:
    """Fake speech-to-text. Takes any audio, returns placeholder text."""

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        # In mock mode, audio content is irrelevant.
        return "[mock-transcription]"


class MockTTS:
    """Fake text-to-speech. Logs what would be spoken, returns silence."""

    async def synthesise(self, text: str) -> bytes:
        # In mock mode, don't actually generate audio.
        return b""
