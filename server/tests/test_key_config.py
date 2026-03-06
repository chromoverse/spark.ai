import unittest

from app.cache.key_config import (
    kernel_recent_events_key,
    query_hash,
    try_extract_user_id,
    user_cache_key,
    user_cache_prefix,
    user_context_key,
    user_context_prefix,
    user_details_key,
    user_embedding_key,
    user_embedding_prefix,
    user_prefix,
    user_recent_messages_key,
    user_sync_cursor_key,
)


class TestKeyConfig(unittest.TestCase):
    def test_user_key_builders(self) -> None:
        user_id = "u123"
        self.assertEqual(user_prefix(user_id), "user:u123:")
        self.assertEqual(user_cache_prefix(user_id), "user:u123:cache:")
        self.assertEqual(user_context_prefix(user_id), "user:u123:ctx:")
        self.assertEqual(user_embedding_prefix(user_id), "user:u123:emb:")
        self.assertEqual(user_details_key(user_id), "user:u123:details")
        self.assertEqual(user_recent_messages_key(user_id), "user:u123:recent_messages")
        self.assertEqual(user_cache_key(user_id, "foo"), "user:u123:cache:foo")
        self.assertEqual(user_embedding_key(user_id, "abc"), "user:u123:emb:abc")
        self.assertEqual(user_sync_cursor_key(user_id), "user:u123:sync:cursor")
        self.assertEqual(kernel_recent_events_key(user_id), "kernel:recent:u123")

    def test_context_key_builder(self) -> None:
        key = user_context_key(
            user_id="u1",
            query_hash="abcd",
            top_k=7,
            threshold=0.123456,
            fast_lane=True,
        )
        self.assertEqual(key, "user:u1:ctx:abcd:k7:t0.1235:f1")

    def test_query_hash_and_user_extract(self) -> None:
        h1 = query_hash(" Hello   World ")
        h2 = query_hash("hello world")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 32)

        self.assertEqual(try_extract_user_id("user:u9:details"), "u9")
        self.assertIsNone(try_extract_user_id("kernel:recent:u9"))


if __name__ == "__main__":
    unittest.main()
