from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class SocketServerAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import app.socket.server as socket_server

        self.socket_server = importlib.reload(socket_server)
        self.socket_server.connected_users.clear()

    async def test_daemon_auth_accepts_service_token(self) -> None:
        with mock.patch.dict(os.environ, {"DAEMON_SERVICE_TOKEN": "daemon-token"}, clear=False):
            save_session = mock.AsyncMock()
            with mock.patch.object(self.socket_server.sio, "save_session", save_session):
                accepted = await self.socket_server.connect(
                    "sid-daemon",
                    {},
                    {"token": "daemon-token", "client_type": "daemon"},
                )

        self.assertTrue(accepted)
        save_session.assert_awaited_once_with(
            "sid-daemon",
            {
                "user_id": "__daemon__",
                "client_type": "daemon",
                "authenticated": True,
            },
        )
        self.assertEqual(self.socket_server.connected_users, {})

    async def test_daemon_auth_rejects_invalid_token(self) -> None:
        with mock.patch.dict(os.environ, {"DAEMON_SERVICE_TOKEN": "daemon-token"}, clear=False):
            with self.assertRaises(ConnectionRefusedError):
                await self.socket_server.connect(
                    "sid-daemon",
                    {},
                    {"token": "wrong-token", "client_type": "daemon"},
                )

    async def test_user_jwt_auth_still_works(self) -> None:
        save_session = mock.AsyncMock()
        with mock.patch.object(self.socket_server.sio, "save_session", save_session):
            with mock.patch.object(
                self.socket_server.jwt,
                "decode_token",
                return_value={"sub": "user-123"},
            ):
                accepted = await self.socket_server.connect(
                    "sid-user",
                    {},
                    {"token": "jwt-token"},
                )

        self.assertTrue(accepted)
        save_session.assert_awaited_once_with(
            "sid-user",
            {
                "user_id": "user-123",
                "client_type": "user",
                "authenticated": True,
            },
        )
        self.assertEqual(self.socket_server.connected_users["user-123"], {"sid-user"})


if __name__ == "__main__":
    unittest.main()
