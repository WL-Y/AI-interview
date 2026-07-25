"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── LLM ──────────────────────────────────────────
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-max"

    # ── Voice (Volcano Engine) ────────────────────────
    volcano_stt_app_id: str = ""
    volcano_stt_token: str = ""
    volcano_tts_app_id: str = ""
    volcano_tts_token: str = ""

    # ── LiveKit ──────────────────────────────────────
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"

    # ── Database ─────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_interview"
    redis_url: str = "redis://localhost:6379/0"

    # ── App ──────────────────────────────────────────
    debug: bool = True
    log_level: str = "INFO"


settings = Settings()
