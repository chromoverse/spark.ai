import unittest

from app.utils.format_context import format_context


class FormatContextRelevanceTests(unittest.TestCase):
    def test_uses_similarity_score_fallback_when_score_missing(self):
        _recent, query_str = format_context(
            [],
            [
                {
                    "content": "Important memory",
                    "_similarity_score": 0.73,
                    "timestamp": "2026-03-05T10:00:00+00:00",
                }
            ],
        )
        self.assertIn("Important memory", query_str)
        self.assertIn("[rel:0.73]", query_str)

    def test_prefers_score_over_similarity_score(self):
        _recent, query_str = format_context(
            [],
            [
                {
                    "content": "High confidence record",
                    "score": 0.91,
                    "_similarity_score": 0.12,
                    "timestamp": "2026-03-05T10:00:00+00:00",
                }
            ],
        )
        self.assertIn("High confidence record", query_str)
        self.assertIn("[rel:0.91]", query_str)


if __name__ == "__main__":
    unittest.main()
