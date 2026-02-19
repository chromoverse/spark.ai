"""
Groq LLM Client — Primary provider using Groq's OpenAI-compatible API.

Uses the openai SDK pointed at https://api.groq.com/openai/v1
Env var: GROQ_API_KEY (JSON array of keys)
Default model: llama-3.3-70b-versatile
"""
import asyncio
import logging
from typing import Any, List, Dict, AsyncGenerator

from openai import OpenAI  # type: ignore[import-untyped]
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_REASONING_MODEL = "openai/gpt-oss-20b"


class GroqClient(BaseClient):
    """Groq provider — fastest inference, primary in fallback chain."""

    def __init__(self) -> None:
        super().__init__(
            provider_name="Groq",
            env_key="GROQ_API_KEY",
            default_model=GROQ_DEFAULT_MODEL,
            default_temperature=0.7,
            default_max_tokens=4096,
        )

    def _create_client(self, api_key: str) -> Any:
        return OpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
            timeout=30.0,
            max_retries=1,
        )
    
    async def _do_chat(self, client, messages, model, temperature, max_tokens) -> str:
        def _call() -> str:
            # Reasoning models (gpt-oss-*) don't support temperature
            is_reasoning = "gpt-oss" in model or "reasoning" in model
            
            kwargs: Dict[str, Any] = dict(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            if not is_reasoning:
                kwargs["temperature"] = temperature  # only add for non-reasoning models

            completion = client.chat.completions.create(**kwargs)
            
            if not completion.choices:
                raise ValueError("Groq returned empty response")
            
            msg = completion.choices[0].message
            content = msg.content or getattr(msg, "reasoning_content", None)
            
            if not content:
                raise ValueError("Groq returned empty response")
            
            return str(content)
        return await asyncio.to_thread(_call)
    async def _do_stream(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """Stream response — runs sync iterator in a thread-safe way."""
        def _create_stream() -> Any:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

        stream = await asyncio.to_thread(_create_stream)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                await asyncio.sleep(0)  # yield control to event loop

    def _extra_quota_keywords(self) -> List[str]:
        """Groq-specific quota error patterns."""
        return ["resource_exhausted"]
