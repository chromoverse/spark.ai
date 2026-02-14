"""
Gemini LLM Client — Google Generative AI provider.

Uses google.generativeai SDK.
Env var: GEMINI_API_KEY (JSON array of keys)
Default model: gemini-2.5-flash
"""
import asyncio
import logging
from typing import Any, List, Dict, Optional, AsyncGenerator

import google.generativeai as genai  # type: ignore[import-untyped]
from app.ai.providers.base_client import BaseClient

logger = logging.getLogger(__name__)

GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient(BaseClient):
    """Gemini provider — second in fallback chain."""

    def __init__(self) -> None:
        super().__init__(
            provider_name="Gemini",
            env_key="GEMINI_API_KEY",
            default_model=GEMINI_DEFAULT_MODEL,
            default_temperature=0.7,
            default_max_tokens=8192,
        )

    def _create_client(self, api_key: str) -> Dict[str, Any]:
        """Return a dict with api_key and model — Gemini needs reconfigure per key."""
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.default_model)
        return {"api_key": api_key, "model": model}

    async def _do_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Gemini chat — wraps sync SDK in thread."""
        genai_model = client["model"]
        api_key: str = client["api_key"]

        # Reconfigure with this key (in case another key was used last)
        genai.configure(api_key=api_key)

        # If a different model is requested, create a new one
        if model != self.default_model:
            genai_model = genai.GenerativeModel(model)

        prompt = self._messages_to_prompt(messages)

        generation_config = {
            "temperature": temperature,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": max_tokens,
        }

        def _call() -> str:
            response = genai_model.generate_content(
                prompt,
                generation_config=generation_config,
            )
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")
            return str(response.text)

        return await asyncio.to_thread(_call)

    async def _do_stream(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """Gemini streaming — wraps sync iterator."""
        genai_model = client["model"]
        api_key: str = client["api_key"]

        genai.configure(api_key=api_key)

        if model != self.default_model:
            genai_model = genai.GenerativeModel(model)

        prompt = self._messages_to_prompt(messages)

        generation_config = {
            "temperature": temperature,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": max_tokens,
        }

        def _create_stream() -> Any:
            return genai_model.generate_content(
                prompt,
                generation_config=generation_config,
                stream=True,
            )

        stream = await asyncio.to_thread(_create_stream)

        for chunk in stream:
            if chunk.text:
                yield chunk.text
                await asyncio.sleep(0)

    def _extra_quota_keywords(self) -> List[str]:
        """Gemini-specific quota error patterns."""
        return ["resource_exhausted"]

    @staticmethod
    def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
        """Convert OpenAI-style messages list to a single prompt string for Gemini."""
        parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(content)
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)