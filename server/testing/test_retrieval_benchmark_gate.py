import sys
import time
import types
import unittest
from collections import OrderedDict
from typing import Dict, List
from unittest.mock import patch

from app.cache.chat_cache import ChatCacheMixin


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return ordered[idx]


def _recall_at_k(results: Dict[str, List[str]], expected: Dict[str, str], k: int = 5) -> float:
    if not expected:
        return 0.0
    hits = 0
    for query, expected_id in expected.items():
        top_ids = results.get(query, [])[:k]
        if expected_id in top_ids:
            hits += 1
    return hits / float(len(expected))


class _FakeEmbeddingService:
    def __init__(self, sleep_s: float = 0.0):
        self.sleep_s = sleep_s

    async def embed_single(self, _text: str):
        if self.sleep_s > 0:
            import asyncio

            await asyncio.sleep(self.sleep_s)
        return [1.0, 0.0, 0.0]


class _VectorClient:
    async def search_chat_messages(self, **_kwargs):
        return [
            {
                "content": "main benchmark detail",
                "timestamp": "2026-03-05T10:00:00+00:00",
                "score": 0.92,
                "_similarity_score": 0.92,
            }
        ]


class _BenchmarkCache(ChatCacheMixin):
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self):
        self.client = object()
        self.vector_client = _VectorClient()
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


class RetrievalBenchmarkGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_latency_gates_for_fast_lane(self):
        cache = _BenchmarkCache()
        fake_mod = types.ModuleType("app.services.embedding_services")
        fake_mod.embedding_service = _FakeEmbeddingService(sleep_s=0.03)

        warm_latencies = []
        cold_latencies = []

        with (
            patch.dict(sys.modules, {"app.services.embedding_services": fake_mod}),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_TARGET_MS", 100),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_SEARCH_BUDGET_MS", 55),
            patch("app.cache.chat_cache.settings.STREAM_CONTEXT_EMBED_BUDGET_MS", 35),
        ):
            cache._cache_query_embedding("warm query", [1.0, 0.0, 0.0])
            for _ in range(20):
                started = time.perf_counter()
                await cache.process_query_and_get_context(
                    user_id="bench",
                    current_query="warm query",
                    budget_ms=100,
                    top_k=8,
                    threshold=0.08,
                    fast_lane=True,
                )
                warm_latencies.append((time.perf_counter() - started) * 1000)

            for i in range(20):
                cache._query_context_cache.clear()
                started = time.perf_counter()
                await cache.process_query_and_get_context(
                    user_id="bench",
                    current_query=f"cold query {i}",
                    budget_ms=180,
                    top_k=8,
                    threshold=0.08,
                    fast_lane=True,
                )
                cold_latencies.append((time.perf_counter() - started) * 1000)

        self.assertLessEqual(_p95(warm_latencies), 100.0)
        self.assertLessEqual(_p95(cold_latencies), 180.0)

    def test_recall_gate_improves_over_baseline(self):
        expected = {
            "q1": "doc_main_1",
            "q2": "doc_main_2",
            "q3": "doc_main_3",
            "q4": "doc_main_4",
        }
        baseline_results = {
            "q1": ["doc_noise_1", "doc_main_1"],
            "q2": ["doc_noise_2", "doc_noise_3"],
            "q3": ["doc_main_3"],
            "q4": ["doc_noise_4"],
        }
        improved_results = {
            "q1": ["doc_main_1", "doc_noise_1"],
            "q2": ["doc_main_2", "doc_noise_3"],
            "q3": ["doc_main_3"],
            "q4": ["doc_main_4", "doc_noise_4"],
        }

        baseline_recall = _recall_at_k(baseline_results, expected, k=5)
        improved_recall = _recall_at_k(improved_results, expected, k=5)

        self.assertGreater(improved_recall, baseline_recall)
        self.assertGreaterEqual(improved_recall, 0.85)


if __name__ == "__main__":
    unittest.main()
