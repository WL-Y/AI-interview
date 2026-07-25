"""Voice provider factory — picks Mock or Real based on config.

Swap between Mock and Volcano by setting env vars:
  - VOLCANO_STT_APP_ID set → uses Volcano STT
  - VOLCANO_STT_APP_ID empty → uses Mock STT
  - VOLCANO_TTS_TOKEN set → uses Volcano TTS
  - VOLCANO_TTS_TOKEN empty → uses Mock TTS
"""

from app.core.config import settings
from app.services.voice.base import SpeechToText, TextToSpeech
from app.services.voice.mock import MockSTT, MockTTS
from app.services.voice.volcano_stt import VolcanoSTT
from app.services.voice.volcano_tts import VolcanoTTS


def create_stt() -> SpeechToText:
    """Return an STT provider (Mock or Volcano)."""
    if settings.volcano_stt_app_id and settings.volcano_stt_token:
        return VolcanoSTT()
    return MockSTT()


def create_tts() -> TextToSpeech:
    """Return a TTS provider (Mock or Volcano)."""
    if settings.volcano_tts_token:
        return VolcanoTTS()
    return MockTTS()
