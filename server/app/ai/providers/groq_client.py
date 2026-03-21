"""
Groq LLM Client — Primary provider using Groq's OpenAI-compatible API.
Uses the openai SDK pointed at https://api.groq.com/openai/v1
Env var: GROQ_API_KEY (JSON array of keys)
"""
import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List

from openai import OpenAI  # type: ignore[import-untyped]
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

GROQ_BASE_URL      = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_SENTINEL = object()


def _is_reasoning(model: str) -> bool:
    return "gpt-oss" in model or "reasoning" in model


class GroqClient(BaseClient):
    """Groq provider — fastest inference, primary in fallback chain."""

    def __init__(self) -> None:
        super().__init__(  # type: ignore[call-arg]
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

    async def _do_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        def _call() -> str:
            kwargs: Dict[str, Any] = {
                "model":      model,
                "messages":   messages,
                "max_tokens": max_tokens,
            }
            if not _is_reasoning(model):
                kwargs["temperature"] = temperature

            completion = client.chat.completions.create(**kwargs)
            if not completion.choices:
                raise ValueError("Groq returned empty choices")

            msg     = completion.choices[0].message
            content = msg.content or getattr(msg, "reasoning_content", None)
            if not content:
                raise ValueError("Groq returned empty content")
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
        """
        Stream via a thread-safe queue.

        FIX: Use asyncio.get_running_loop() (not get_event_loop()) and cache
        the reference once — both the producer thread and run_in_executor call
        must use the exact same loop object to avoid dropped chunks / hangs.
        """
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()   # ← FIX: get_running_loop, stored once

        def _produce() -> None:
            """Runs in a thread — iterates the sync stream, pushes to queue."""
            try:
                kwargs: Dict[str, Any] = {
                    "model":      model,
                    "messages":   messages,
                    "max_tokens": max_tokens,
                    "stream":     True,
                }
                if not _is_reasoning(model):
                    kwargs["temperature"] = temperature

                stream = client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    text  = delta.content or getattr(delta, "reasoning_content", None)
                    if text:
                        asyncio.run_coroutine_threadsafe(queue.put(str(text)), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(_SENTINEL), loop)

        loop.run_in_executor(None, _produce)   # ← FIX: use cached loop

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    def _extra_quota_keywords(self) -> List[str]:
        return ["resource_exhausted"]