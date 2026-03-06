import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_STREAM_SERVICE_PATH = _SERVER_ROOT / "app" / "services" / "chat" / "stream_service.py"

if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

_SPEC = importlib.util.spec_from_file_location("stream_service_under_test", _STREAM_SERVICE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Unable to load stream_service module for tests")
stream_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stream_module)

StreamService = stream_module.StreamService
_find_split_point = stream_module._find_split_point


class _FakeSocket:
    async def emit(self, event, payload, to=None):
        return None


class _FakeTTSService:
    def __init__(self):
        self.calls: list[str] = []

    async def stream_to_socket(self, **kwargs):
        self.calls.append(kwargs.get("text", ""))
        return True


class StreamServiceLatencyTests(unittest.IsolatedAsyncioTestCase):
    def test_intent_gate_avoids_internal_status_queries(self):
        self.assertFalse(
            stream_module._is_live_or_tool_intent(
                "what is the current status of our server and how many tools do we have"
            )
        )
        self.assertTrue(stream_module._is_live_or_tool_intent("open camera now"))

    def test_find_split_point_prefers_sentence_boundary(self):
        text = "Hello boss. Let us continue with the task right now"
        split_at = _find_split_point(text, min_words=2, soft_words=4, max_words=20)
        self.assertGreater(split_at, 0)
        self.assertTrue(text[:split_at].strip().endswith("."))

    def test_find_split_point_forces_at_max_words(self):
        text = "one two three four five six seven eight nine ten"
        split_at = _find_split_point(text, min_words=2, soft_words=8, max_words=4)
        self.assertEqual(len(text[:split_at].split()), 4)

    async def test_stream_falls_back_to_chat_when_stream_fails_before_first_chunk(self):
        async def _failing_stream(*args, **kwargs):
            if False:
                yield ""
            raise RuntimeError("stream failure")

        async def _chat_fallback(*args, **kwargs):
            return "Fallback response from chat.", "Groq"

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=[]),
            patch.object(stream_module, "process_query_and_get_context", return_value=([], False)),
            patch.object(stream_module, "_iter_stream_with_fast_model", _failing_stream),
            patch.object(stream_module, "_chat_with_fast_model", _chat_fallback),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 8),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="hello there",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertGreaterEqual(len(tts.calls), 1)
        self.assertIn("Fallback response from chat.", tts.calls[0])

    async def test_stream_preserves_chunk_emit_order(self):
        async def _stream_tokens(*args, **kwargs):
            for token in ["Hello boss. ", "I can help with that now. ", "Tell me the next step."]:
                yield token

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=[]),
            patch.object(stream_module, "process_query_and_get_context", return_value=([], False)),
            patch.object(stream_module, "_iter_stream_with_fast_model", _stream_tokens),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 12),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="hello there",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertGreaterEqual(len(tts.calls), 2)
        self.assertTrue(tts.calls[0].startswith("Hello boss."))

    async def test_context_timeout_does_not_block_stream_output(self):
        async def _slow_context(*args, **kwargs):
            await asyncio.sleep(0.15)
            return [], False

        async def _stream_tokens(*args, **kwargs):
            yield "This should still be spoken quickly."

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=[]),
            patch.object(stream_module, "process_query_and_get_context", _slow_context),
            patch.object(stream_module, "_iter_stream_with_fast_model", _stream_tokens),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CONTEXT_BUDGET_MS", 50),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 12),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="time out context",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertGreaterEqual(len(tts.calls), 1)

    async def test_stream_uses_tuned_context_defaults(self):
        async def _stream_tokens(*args, **kwargs):
            yield "I have enough context now."

        context_mock = AsyncMock(return_value=([{"content": "timeline detail", "score": 0.91}], False))

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=[]),
            patch.object(stream_module, "process_query_and_get_context", context_mock),
            patch.object(stream_module, "_iter_stream_with_fast_model", _stream_tokens),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CONTEXT_TARGET_MS", 100),
            patch.object(settings, "STREAM_CONTEXT_TOP_K", 8),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 12),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="what is my project timeline",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertTrue(context_mock.await_count >= 1)
        self.assertEqual(context_mock.call_args.kwargs["budget_ms"], 100)
        self.assertEqual(context_mock.call_args.kwargs["top_k"], 8)
        self.assertEqual(context_mock.call_args.kwargs["threshold"], 0.08)
        self.assertTrue(context_mock.call_args.kwargs["fast_lane"])

    async def test_stream_injects_successful_query_context_into_prompt(self):
        async def _stream_tokens(*args, **kwargs):
            yield "Using your memory now."

        captured: dict[str, object] = {}

        def _capture_prompt(**kwargs):
            captured["query_context"] = kwargs.get("query_context")
            return "Mock prompt"

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=[]),
            patch.object(
                stream_module,
                "process_query_and_get_context",
                AsyncMock(return_value=([{"content": "main data", "score": 0.88}], False)),
            ),
            patch.object(stream_module, "_build_stream_prompt", side_effect=_capture_prompt),
            patch.object(stream_module, "_iter_stream_with_fast_model", _stream_tokens),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 12),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="remind me my main data",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertIn("query_context", captured)
        query_context = captured["query_context"]
        self.assertIsInstance(query_context, list)
        self.assertEqual(query_context[0]["content"], "main data")
        self.assertAlmostEqual(query_context[0]["score"], 0.88, places=2)

    async def test_stream_recovers_query_context_from_recent_when_retrieval_empty(self):
        async def _stream_tokens(*args, **kwargs):
            yield "Recovered from recent messages."

        captured: dict[str, object] = {}

        def _capture_prompt(**kwargs):
            captured["query_context"] = kwargs.get("query_context")
            return "Mock prompt"

        recent_messages = [
            {
                "role": "user",
                "content": "Hey Spark, sing song using meow meow and try to impress your CEO using your humor.",
                "timestamp": "2026-03-06T12:30:15.559988+05:45",
            },
            {
                "role": "assistant",
                "content": "Sure, here's a meow-inspired song.",
                "timestamp": "2026-03-06T12:30:18.124406+05:45",
            },
        ]

        with (
            patch.object(stream_module, "load_user", return_value={"language": "en"}),
            patch.object(stream_module, "get_last_n_messages", return_value=recent_messages),
            patch.object(
                stream_module,
                "process_query_and_get_context",
                AsyncMock(return_value=([], False)),
            ),
            patch.object(stream_module, "_build_stream_prompt", side_effect=_capture_prompt),
            patch.object(stream_module, "_iter_stream_with_fast_model", _stream_tokens),
            patch.object(settings, "STREAM_USE_LLM_STREAM", True),
            patch.object(settings, "STREAM_USE_COMPACT_PROMPT", True),
            patch.object(settings, "STREAM_CHUNK_MIN_WORDS", 2),
            patch.object(settings, "STREAM_CHUNK_SOFT_WORDS", 3),
            patch.object(settings, "STREAM_CHUNK_MAX_WORDS", 12),
            patch.object(settings, "STREAM_CONTEXT_TOP_K", 8),
            patch.object(settings, "environment", "PRODUCTION"),
        ):
            service = StreamService()
            tts = _FakeTTSService()
            ok = await service.stream_chat_with_tts(
                query="meow meow song",
                user_id="u1",
                sio=_FakeSocket(),
                sid="sid1",
                tts_service=tts,
                gender="female",
            )

        self.assertTrue(ok)
        self.assertIn("query_context", captured)
        query_context = captured["query_context"]
        self.assertIsInstance(query_context, list)
        self.assertGreaterEqual(len(query_context), 1)
        self.assertIn("meow", query_context[0]["content"].lower())
        self.assertTrue(str(query_context[0].get("_fallback_source", "")).startswith("stream_recent_"))


if __name__ == "__main__":
    unittest.main()
