
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from app.ai.providers.base_client import BaseClient, AllKeysExhaustedError, QuotaError

class MockProvider(BaseClient):
    def __init__(self):
        # Mock key_manager functions
        self._keys = ["key1", "key2"]
        self._failed_keys = set()
        self._lock = asyncio.Lock()
        self.provider_name = "MockProvider"
        self.env_key = "MOCK_KEY"
        self.default_model = "mock-model"
        self.default_temperature = 0.5
        self.default_max_tokens = 100
        self._clients = {}
        
    def _create_client(self, api_key):
        return MagicMock()

    # Override key management to avoid hitting key_manager
    def _get_active_key(self):
        for k in self._keys:
            if k not in self._failed_keys:
                return k
        return None

    def _mark_key_failed(self, key):
        self._failed_keys.add(key)

    def _rotate_key(self):
        pass # No-op for this simple mock

    
    async def _do_chat(self, client, messages, model, temperature, max_tokens):
        # Default behavior: Raise an exception based on the key
        # This will be overridden in tests using side_effect
        pass

    async def _do_stream(self, client, messages, model, temperature, max_tokens):
        yield ""

class TestBaseClientErrorHandling(unittest.TestCase):
    def setUp(self):
        self.provider = MockProvider()

    def test_quota_error_rotates_key(self):
        """Test that QuotaError causes key rotation."""
        # Setup: key1 fails with QuotaError, key2 succeeds
        self.provider._do_chat = AsyncMock(side_effect=[
            QuotaError("Rate limit exceeded"), # key1
            "Success"                          # key2
        ])
        
        # Act
        response = asyncio.run(self.provider.llm_chat([]))
        
        # Assert
        self.assertEqual(response, "Success")
        self.assertEqual(len(self.provider._failed_keys), 1)
        self.assertIn("key1", self.provider._failed_keys)

    def test_transient_error_raises_without_burning_key(self):
        """Test that transient errors raise to caller WITHOUT marking the key as failed."""
        self.provider._do_chat = AsyncMock(side_effect=ValueError("Transient error"))
        
        # Act & Assert — should raise (retry lives inside _do_chat, not BaseClient)
        with self.assertRaises(ValueError):
            asyncio.run(self.provider.llm_chat([]))
            
        # Key must NOT be marked as failed
        self.assertEqual(len(self.provider._failed_keys), 0)

if __name__ == "__main__":
    unittest.main()
