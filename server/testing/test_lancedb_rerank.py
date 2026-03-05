import unittest
from collections import OrderedDict

import pandas as pd

from app.cache.lancedb_manager import LanceDBManager


class _FakeSearchQuery:
    def __init__(self, rows):
        self._rows = rows

    def where(self, _clause):
        return self

    def limit(self, _n):
        return self

    def to_pandas(self):
        return pd.DataFrame(self._rows)


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def search(self, _query_vector):
        return _FakeSearchQuery(self._rows)


class LanceDBRerankTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_cosine_rerank_promotes_main_result(self):
        rows = [
            {
                "id": "doc_noise",
                "user_id": "u1",
                "role": "user",
                "content": "noise detail",
                "timestamp": "2026-03-05T10:00:00+00:00",
                "vector": [0.0, 1.0],
                "_distance": 0.05,
            },
            {
                "id": "doc_main",
                "user_id": "u1",
                "role": "user",
                "content": "main detail",
                "timestamp": "2026-03-05T10:01:00+00:00",
                "vector": [0.99, 0.01],
                "_distance": 0.20,
            },
        ]

        manager = LanceDBManager.__new__(LanceDBManager)
        manager._table = _FakeTable(rows)
        manager._chat_cache = OrderedDict()

        results = await manager.search_chat_messages(
            user_id="u1",
            query_vector=[1.0, 0.0],
            limit=2,
            threshold=0.0,
            candidate_limit=4,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "doc_main")
        self.assertIn("score", results[0])
        self.assertIn("_similarity_score", results[0])


if __name__ == "__main__":
    unittest.main()
