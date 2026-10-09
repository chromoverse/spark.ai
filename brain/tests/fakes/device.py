from __future__ import annotations

import asyncio
import uuid
from typing import Any

import socketio

NS = "/v2"


class FakeDevice:
    """An in-process body speaking gateway protocol v2 over a real Socket.IO connection."""

    def __init__(self, url: str, tokens: dict[str, Any]) -> None:
        self.url = url
        self.access_token: str = tokens["access_token"]
        self.device_id: str = tokens["device_id"]
        self.inbox: list[tuple[str, dict[str, Any]]] = []
        self.disconnected = asyncio.Event()
        self._arrived = asyncio.Condition()
        self.sio = socketio.AsyncClient(reconnection=False)
        self.sio.on("*", self._any, namespace=NS)
        self.sio.on("disconnect", self._gone, namespace=NS)

    async def _any(self, event: str, data: dict[str, Any]) -> None:
        async with self._arrived:
            self.inbox.append((event, data))
            self._arrived.notify_all()

    async def _gone(self, *_: Any) -> None:
        self.disconnected.set()

    async def connect(self, auth: dict[str, Any] | None = None) -> None:
        await self.sio.connect(
            self.url,
            namespaces=[NS],
            transports=["websocket"],
            auth=auth
            if auth is not None
            else {"token": self.access_token, "device_id": self.device_id},
            wait_timeout=5,
        )

    async def call(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = {"v": 2, "id": uuid.uuid4().hex, "ts": 0, "trace_id": uuid.uuid4().hex}
        result: dict[str, Any] = await self.sio.call(
            event, envelope | payload, namespace=NS, timeout=5
        )
        return result

    async def hello(self, **overrides: Any) -> dict[str, Any]:
        payload = {
            "platform": "win32",
            "app_version": "2.0.0-test",
            "capabilities": ["apps", "volume", "files"],
            "tool_versions": {"app_open": "1"},
            "hardware": {"cpu": "fake", "ram_gb": 16},
        } | overrides
        return await self.call("device.hello", payload)

    async def next(self, event: str, within: float = 3) -> dict[str, Any]:
        """Waits for (and consumes) the next `event` from the brain."""
        async with asyncio.timeout(within), self._arrived:
            while True:
                for i, (name, data) in enumerate(self.inbox):
                    if name == event:
                        del self.inbox[i]
                        return data
                await self._arrived.wait()

    async def close(self) -> None:
        if self.sio.connected:
            await self.sio.disconnect()
