"""
Mistral LLM Client — OpenAI-compatible API at https://api.mistral.ai/v1
Env var: MISTRAL_API_KEY (JSON array of keys)
"""
import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List

from openai import OpenAI
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_DEFAULT_MODEL = "mistral-small-latest"

_SENTINEL = object()


class MistralClient(BaseClient):
    """Mistral provider — ~1B tokens/month free, good for summarization."""

    def __init__(self) -> None:
        super().__init__(
            provider_name="Mistral",
            env_key="MISTRAL_API_KEY",
            default_model=MISTRAL_DEFAULT_MODEL,
            default_temperature=0.7,
            default_max_tokens=4096,
        )

    def _create_client(self, api_key: str) -> Any:
        return OpenAI(api_key=api_key, base_url=MISTRAL_BASE_URL, timeout=30.0, max_retries=1)

    async def _do_chat(self, client: Any, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> str:
        def _call() -> str:
            completion = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
            )
            if not completion.choices:
                raise ValueError("Mistral returned empty choices")
            content = completion.choices[0].message.content
            if not content:
                raise ValueError("Mistral returned empty content")
            return str(content)
        return await asyncio.to_thread(_call)

    async def _do_stream(self, client: Any, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                stream = client.chat.completions.create(
                    model=model, messages=messages, temperature=temperature, max_tokens=max_tokens, stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        asyncio.run_coroutine_threadsafe(queue.put(chunk.choices[0].delta.content), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(_SENTINEL), loop)

        loop.run_in_executor(None, _produce)
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
