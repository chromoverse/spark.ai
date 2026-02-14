"""
OpenRouter LLM Client — Last-resort fallback provider.

Uses OpenAI SDK pointed at https://openrouter.ai/api/v1
Env var: OPENROUTER_API_KEY (JSON array of keys)
"""
import asyncio
import logging
from typing import Any, List, Dict, Optional, AsyncGenerator

from openai import OpenAI  # type: ignore[import-untyped]
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-r1-0528"

# Headers required by OpenRouter TOS
OPENROUTER_HEADERS: Dict[str, str] = {
    "HTTP-Referer": "https://siddhantyadav.com.np",
    "X-Title": "Siddy Coddy",
}


class OpenRouterClient(BaseClient):
    """OpenRouter provider — third in fallback chain (last resort)."""

    def __init__(self, default_model: Optional[str] = None) -> None:
        super().__init__(
            provider_name="OpenRouter",
            env_key="OPENROUTER_API_KEY",
            default_model=default_model or OPENROUTER_DEFAULT_MODEL,
            default_temperature=0.7,
            default_max_tokens=4096,
        )

    def _create_client(self, api_key: str) -> Any:
        return OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=30.0,
            max_retries=1,
        )

    async def _do_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        def _call() -> str:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers=OPENROUTER_HEADERS,
            )

            if not completion.choices:
                raise ValueError("OpenRouter returned no choices")

            content: Optional[str] = completion.choices[0].message.content
            if content is None or not content.strip():
                finish_reason = completion.choices[0].finish_reason
                if finish_reason == "content_filter":
                    raise ValueError("Response blocked by content filter")
                raise ValueError(f"Empty response (finish_reason: {finish_reason})")

            return content

        return await asyncio.to_thread(_call)

    async def _do_stream(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        def _create_stream() -> Any:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                extra_headers=OPENROUTER_HEADERS,
            )

        stream = await asyncio.to_thread(_create_stream)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                await asyncio.sleep(0)

    def _extra_quota_keywords(self) -> List[str]:
        """OpenRouter-specific quota error patterns."""
        return ["balance"]