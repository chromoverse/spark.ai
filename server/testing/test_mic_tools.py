import unittest
from unittest.mock import AsyncMock, patch

from tools.tools.system.microphone import (
    MIC_CONTROL_SOCKET_EVENT,
    MicMuteTool,
    MicUnmuteTool,
)


class MicControlToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mic_mute_emits_socket_event_for_user(self):
        tool = MicMuteTool()

        with patch(
            "tools.tools.system.microphone.socket_emit",
            new_callable=AsyncMock,
        ) as mock_socket_emit:
            mock_socket_emit.return_value = True

            result = await tool.execute({"_user_id": "user-123"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["action"], "mute")
        self.assertTrue(result.data["mic_muted"])

        args = mock_socket_emit.await_args.args
        kwargs = mock_socket_emit.await_args.kwargs

        self.assertEqual(args[0], MIC_CONTROL_SOCKET_EVENT)
        self.assertEqual(args[1]["action"], "mute")
        self.assertEqual(args[1]["source"], "tool")
        self.assertEqual(kwargs["user_id"], "user-123")

    async def test_mic_unmute_uses_user_id_fallback(self):
        tool = MicUnmuteTool()

        with patch(
            "tools.tools.system.microphone.socket_emit",
            new_callable=AsyncMock,
        ) as mock_socket_emit:
            mock_socket_emit.return_value = True

            result = await tool.execute({"user_id": "user-456"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["action"], "unmute")
        self.assertFalse(result.data["mic_muted"])

        args = mock_socket_emit.await_args.args
        kwargs = mock_socket_emit.await_args.kwargs
        self.assertEqual(args[0], MIC_CONTROL_SOCKET_EVENT)
        self.assertEqual(args[1]["action"], "unmute")
        self.assertEqual(kwargs["user_id"], "user-456")

    async def test_tool_fails_without_user_context(self):
        tool = MicMuteTool()

        result = await tool.execute({})

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Missing required parameter: user_id")


if __name__ == "__main__":
    unittest.main()
