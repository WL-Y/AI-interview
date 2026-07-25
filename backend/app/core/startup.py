"""Application startup checks — validates environment before serving requests."""

import logging

from app.core.config import settings
from app.services.llm_service import has_real_llm

logger = logging.getLogger(__name__)


def run_startup_checks():
    """Run validation on app startup. Logs warnings, does not abort."""
    checks = []

    # LLM check
    if not has_real_llm():
        logger.warning(
            "NO_LLM: 未配置 LLM API Key。所有 AI 调用将使用 Mock 模式。"
            "设置 DEEPSEEK_API_KEY 或 QWEN_API_KEY 启用真实 LLM。"
        )
    else:
        if settings.deepseek_api_key:
            logger.info("LLM primary: DeepSeek (%s)", settings.deepseek_model)
        if settings.qwen_api_key:
            logger.info("LLM fallback: Qwen (%s)", settings.qwen_model)

    # Voice check
    if not settings.volcano_stt_app_id or not settings.volcano_stt_token:
        logger.warning(
            "NO_STT: 未配置火山引擎 STT。语音识别将使用 Mock 模式。"
            "设置 VOLCANO_STT_APP_ID 和 VOLCANO_STT_TOKEN 启用。"
        )
    if not settings.volcano_tts_token:
        logger.warning(
            "NO_TTS: 未配置火山引擎 TTS。语音合成将使用 Mock 模式。"
            "设置 VOLCANO_TTS_TOKEN 启用。"
        )

    # LiveKit check
    if "localhost" in settings.livekit_url:
        logger.info("LiveKit: using local instance (%s)", settings.livekit_url)
    else:
        logger.info("LiveKit: using remote instance (%s)", settings.livekit_url)

    # Database check
    if "localhost" in settings.database_url:
        logger.info("Database: PostgreSQL at localhost")

    if "localhost" in settings.redis_url:
        logger.info("Cache: Redis at localhost")

    logger.info("Startup checks complete. %s warnings.", len(checks))
