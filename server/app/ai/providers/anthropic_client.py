"""
Anthropic LLM Client — Claude, via the official anthropic SDK.
Env var: ANTHROPIC_API_KEY (JSON array of keys)
Default model: claude-opus-5-5

Claude Opus 5.5 rejects temperature and always thinks, so temperature is
ignored and max_tokens has a floor (thinking spends from the same budget).
"""
import logging
from typing import Any, AsyncGenerator, Dict, List

from anthropic import AsyncAnthropic
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
# Callers cap answers at 60-300 tokens; thinking would eat a cap that small.
_MIN_MAX_TOKENS = 16000
# Spark's replies are spoken aloud, so keep thinking short and the first word fast.
_EFFORT = "low"


class AnthropicClient(BaseClient):
    """Anthropic provider — first in the streaming (main chat) chain."""

    def __init__(self) -> None:
        super().__init__(
            provider_name="Anthropic",
            env_key="ANTHROPIC_API_KEY",
            default_model=ANTHROPIC_DEFAULT_MODEL,
            default_max_tokens=_MIN_MAX_TOKENS,
        )

    def _create_client(self, api_key: str) -> Any:
        return AsyncAnthropic(api_key=api_key, timeout=60.0, max_retries=0)

    async def _do_chat(self, client: Any, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> str:
        response = await client.beta.messages.create(**_request(messages, model, max_tokens))
        if response.stop_reason == "refusal":
            raise ValueError("Anthropic refused the request")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise ValueError("Anthropic returned empty content")
        return text

    async def _do_stream(self, client: Any, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> AsyncGenerator[str, None]:
        async with client.beta.messages.stream(**_request(messages, model, max_tokens)) as stream:
            async for text in stream.text_stream:
                yield text


def _request(messages: List[Dict[str, str]], model: str, max_tokens: int) -> Dict[str, Any]:
    """OpenAI-style messages → a Messages API request (system lifted out, user turn first)."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system" and m.get("content"))
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    while turns and turns[0]["role"] == "assistant":
        turns.pop(0)
    request: Dict[str, Any] = {
        "model": model,
        "max_tokens": max(max_tokens, _MIN_MAX_TOKENS),
        "messages": turns,
        "output_config": {"effort": _EFFORT},
        # A declined request re-runs server-side on Anthropic's recommended fallback model.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    if system:
        request["system"] = system
    return request


if __name__ == "__main__":
    req = _request(
        [
            {"role": "system", "content": "rules"},
            {"role": "assistant", "content": "stale greeting"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "open spotify"},
        ],
        ANTHROPIC_DEFAULT_MODEL,
        60,
    )
    assert req["system"] == "rules"
    assert req["messages"] == [{"role": "user", "content": "open spotify"}]
    assert req["max_tokens"] == _MIN_MAX_TOKENS
    assert "temperature" not in req
    print("ok")
