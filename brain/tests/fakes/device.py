from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
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
        self.refusals: list[Any] = []  # connect_error payloads from the brain
        # tool name → tool.result payload ({"ok": True, "output": …} or {"ok": False, "error": …});
        # a tool.call for one of these is answered automatically after `before_result()`.
        self.tools: dict[str, dict[str, Any]] = {}
        self.before_result: Callable[[], Awaitable[None]] | None = None
        self._replies: set[asyncio.Task[None]] = set()
        self._arrived = asyncio.Condition()
        self.sio = socketio.AsyncClient(reconnection=False)
        self.sio.on("*", self._any, namespace=NS)
        self.sio.on("disconnect", self._gone, namespace=NS)
        self.sio.on("connect_error", self._refused, namespace=NS)

    async def _any(self, event: str, data: dict[str, Any]) -> None:
        async with self._arrived:
            self.inbox.append((event, data))
            self._arrived.notify_all()
        if event == "tool.call" and data["tool"] in self.tools:
            task = asyncio.create_task(self._run_tool(data))
            self._replies.add(task)
            task.add_done_callback(self._replies.discard)

    async def _run_tool(self, call: dict[str, Any]) -> None:
        if self.before_result is not None:
            await self.before_result()
        await self.call("tool.result", {"call_id": call["call_id"], **self.tools[call["tool"]]})

    async def _refused(self, data: Any) -> None:
        self.refusals.append(data)

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

    async def say(self, text: str, **extra: Any) -> tuple[str, dict[str, Any]]:
        """Sends signal.final; returns (signal_id, ack)."""
        signal_id = extra.pop("signal_id", None) or uuid.uuid4().hex
        ack = await self.call("signal.final", {"signal_id": signal_id, "text": text, **extra})
        return signal_id, ack

    async def reply(self, signal_id: str, within: float = 5) -> list[dict[str, Any]]:
        """reply.delta events for the signal up to and including the final marker."""
        out: list[dict[str, Any]] = []
        while True:
            delta = await self.next("reply.delta", within)
            if delta["signal_id"] != signal_id:
                continue
            out.append(delta)
            if delta["final"]:
                return out

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
        for task in list(self._replies):
            task.cancel()
        if self.sio.connected:
            await self.sio.disconnect()
