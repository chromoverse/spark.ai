import asyncio
import sys
import types
import unittest
from collections import OrderedDict
from unittest.mock import patch

from app.cache.chat_cache import ChatCacheMixin


class _FakeEmbeddingService:
    def __init__(self, sleep_s: float = 0.0):
        self.sleep_s = sleep_s

    async def embed_single(self, _text: str):
        if self.sleep_s > 0:
            await asyncio.sleep(self.sleep_s)
        return [1.0, 0.0, 0.0]


class _SequenceVectorClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def search_chat_messages(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


class _TestChatCache(ChatCacheMixin):
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self, vector_client):
        # Isolate class-level caches for deterministic tests.
        self.client = object()
        self.vector_client = vector_client
        self._query_context_cache = OrderedDict()
        self._query_emb_cache = OrderedDict()

    async def _ensure_client(self):
        return None

    def _get_vector_client(self):
        return self.vector_client

    async def add_message_with_embedding(self, *args, **kwargs):
        return None

    async def _append_message_to_local_and_cloud(self, *args, **kwargs):
        return None


class ChatContextQualityTests(unittest.IsolatedAsyncioTestCase):
    def _fake_embedding_module(self, sleep_s: float = 0.0):
        mod = types.ModuleType("app.services.embedding_services")
        mod.embedding_service = _FakeEmbeddingService(sleep_s=sleep_s)
        return mod

    async def test_timeout_empty_result_does_not_poison_next_lookup(self):
        vector_client = _SequenceVectorClient(
            responses=[
                [
                    {
                        "content": "main memory",
                        "timestamp": "2026-03-05T10:00:00+00:00",
                        "score": 0.92,
                        "_similarity_score": 0.92,
                    }
                ]
            ]
        )
        cache = _TestChatCache(vector_client=vector_client)
        fake_embedding_mod = self._fake_embedding_module(sleep_s=0.05)

        with (
            patch.dict(sys.modules, {"app.services.embedding_services": fake_embedding_mod}),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_CACHE_EMPTY_RESULTS", False),
        ):
            context1, _ = await cache.process_query_and_get_context(
                user_id="u1",
                current_query="where is main memory",
                budget_ms=1,
                top_k=6,
                threshold=0.1,
                fast_lane=True,
            )
            self.assertEqual(context1, [])

            cache._cache_query_embedding("where is main memory", [1.0, 0.0, 0.0])
            context2, _ = await cache.process_query_and_get_context(
                user_id="u1",
                current_query="where is main memory",
                budget_ms=120,
                top_k=6,
                threshold=0.1,
                fast_lane=True,
            )

        self.assertGreaterEqual(len(context2), 1)
        self.assertEqual(context2[0]["content"], "main memory")
        self.assertGreaterEqual(len(vector_client.calls), 1)

    async def test_query_context_cache_key_isolated_by_params(self):
        cache = _TestChatCache(vector_client=_SequenceVectorClient(responses=[[]]))

        cache._set_query_context_cache(
            user_id="u1",
            query="same query",
            context=[{"content": "fast lane"}],
            pinecone_flag=False,
            top_k=6,
            threshold=0.1,
            fast_lane=True,
        )
        cache._set_query_context_cache(
            user_id="u1",
            query="same query",
            context=[{"content": "slow lane"}],
            pinecone_flag=False,
            top_k=10,
            threshold=0.2,
            fast_lane=False,
        )

        fast = cache._get_query_context_cache(
            user_id="u1",
            query="same query",
            top_k=6,
            threshold=0.1,
            fast_lane=True,
        )
        slow = cache._get_query_context_cache(
            user_id="u1",
            query="same query",
            top_k=10,
            threshold=0.2,
            fast_lane=False,
        )

        self.assertIsNotNone(fast)
        self.assertIsNotNone(slow)
        self.assertEqual(fast[0][0]["content"], "fast lane")
        self.assertEqual(slow[0][0]["content"], "slow lane")

    async def test_second_pass_can_recover_main_result(self):
        vector_client = _SequenceVectorClient(
            responses=[
                [
                    {
                        "content": "weak detail",
                        "timestamp": "2026-03-05T10:00:00+00:00",
                        "score": 0.12,
                        "_similarity_score": 0.12,
                    }
                ],
                [
                    {
                        "content": "main detail",
                        "timestamp": "2026-03-05T10:01:00+00:00",
                        "score": 0.93,
                        "_similarity_score": 0.93,
                    },
                    {
                        "content": "weak detail",
                        "timestamp": "2026-03-05T10:00:00+00:00",
                        "score": 0.12,
                        "_similarity_score": 0.12,
                    },
                ],
            ]
        )
        cache = _TestChatCache(vector_client=vector_client)
        cache._cache_query_embedding("find main detail", [1.0, 0.0, 0.0])
        fake_embedding_mod = self._fake_embedding_module(sleep_s=0.0)

        with (
            patch.dict(sys.modules, {"app.services.embedding_services": fake_embedding_mod}),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_MIN_RESULTS", 2),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_LOW_SCORE", 0.22),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_SEARCH_BUDGET_MS", 60),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_CACHE_EMPTY_RESULTS", False),
        ):
            context, _ = await cache.process_query_and_get_context(
                user_id="u1",
                current_query="find main detail",
                budget_ms=120,
                top_k=3,
                threshold=0.1,
                fast_lane=True,
            )

        self.assertGreaterEqual(len(vector_client.calls), 2)
        self.assertGreaterEqual(len(context), 1)
        self.assertEqual(context[0]["content"], "main detail")


if __name__ == "__main__":
    unittest.main()
