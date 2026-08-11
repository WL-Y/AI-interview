"""LLM service — DeepSeek (primary) + Qwen (fallback) with timeout & retry.

Uses httpx directly (no LangChain dependency) for OpenAI-compatible chat API.
Fallback chain: DeepSeek ─timeout→ Qwen ─error→ Mock echo
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import certifi
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PRIMARY_TIMEOUT = 10.0      # seconds for normal requests
BATCH_TIMEOUT = 45.0        # seconds for batch operations (e.g. personalise all questions)


# ═══════════════════════════════════════════════════════════
# Low-level API call
# ═══════════════════════════════════════════════════════════

async def _call_openai_compatible(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 30.0,
    max_tokens: int = 2048,
    temperature: float = 1.0,  # DeepSeek 推荐 temperature=1.0
) -> str:
    """Call any OpenAI-compatible chat completions endpoint."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking": {"type": "disabled"},  # 面试不需要 thinking，节省 token
    }

    async with httpx.AsyncClient(timeout=timeout, verify=certifi.where()) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

async def llm_invoke(
    prompt: str,
    system_prompt: str = "",
    use_fallback: bool = False,
    timeout: Optional[float] = None,
) -> str:
    """Invoke LLM with automatic fallback.

    Chain: DeepSeek (timeout) → Qwen → Mock echo

    Args:
        timeout: Override the primary timeout (seconds). None = use PRIMARY_TIMEOUT.
    """
    effective_timeout = timeout if timeout is not None else PRIMARY_TIMEOUT

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # ── Try primary (DeepSeek) ─────────────────────────
    if not use_fallback and settings.deepseek_api_key:
        try:
            return await asyncio.wait_for(
                _call_openai_compatible(
                    messages=messages,
                    base_url=settings.deepseek_base_url,
                    api_key=settings.deepseek_api_key,
                    model=settings.deepseek_model,
                    timeout=effective_timeout,
                ),
                timeout=effective_timeout + 3,
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("DeepSeek failed (%.1fs): %s", effective_timeout, e)

    # ── Try fallback (Qwen) ────────────────────────────
    if settings.qwen_api_key and not (use_fallback and not settings.qwen_api_key):
        try:
            return await _call_openai_compatible(
                messages=messages,
                base_url=settings.qwen_base_url,
                api_key=settings.qwen_api_key,
                model=settings.qwen_model,
                timeout=10.0,
            )
        except Exception as e:
            logger.error("Qwen fallback also failed: %s", e)

    # ── Ultimate fallback: Mock echo ────────────────────
    return _mock_response(prompt)


def _mock_response(prompt: str) -> str:
    """Return a mock response when no LLM is available."""
    # If the prompt asks for JSON, return a valid JSON stub
    if "JSON" in prompt or "json" in prompt.lower():
        if "score" in prompt.lower():
            return json.dumps({
                "score": 3,
                "summary": "Mock 模式下的回答摘要。",
                "notes": "未配置 LLM API Key，使用模拟评分。",
            }, ensure_ascii=False)
        if "overall_score" in prompt:
            return json.dumps({
                "overall_score": 3.0,
                "dimension_scores": [
                    {"dimension": "tech_depth", "score": 3, "comment": "Mock 模式评分"},
                    {"dimension": "project_experience", "score": 3, "comment": "Mock 模式评分"},
                    {"dimension": "communication", "score": 3, "comment": "Mock 模式评分"},
                    {"dimension": "role_fit", "score": 3, "comment": "Mock 模式评分"},
                ],
                "strengths": ["Mock 模式 - 亮点未分析"],
                "weaknesses": ["Mock 模式 - 待改进未分析"],
                "improvement_plan": "配置 DeepSeek 或 Qwen API Key 即可获得真实评分。",
            }, ensure_ascii=False)
    return f"[Mock] 收到: {prompt[:80]}..."


def has_real_llm() -> bool:
    """Check if any real LLM API key is configured."""
    return bool(settings.deepseek_api_key or settings.qwen_api_key)
