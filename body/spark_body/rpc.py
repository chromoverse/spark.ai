"""JSON-RPC 2.0 with Electron main over stdio (API.md §4). One JSON object per line (NDJSON):
simple to frame, and Node's readline splits it for free. stdout is the channel, so logs go to
stderr. Requests run as concurrent tasks so a long `fitness.run` never blocks `tts.stop`."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

PARSE_ERROR, INVALID_REQUEST, NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _stdout(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


class Rpc:
    def __init__(self, write: Callable[[bytes], None] = _stdout) -> None:
        self.methods: dict[str, Handler] = {}
        self._write = write
        self.tasks: set[asyncio.Task[Any]] = set()

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self.methods[name] = fn
            return fn

        return register

    def _send(self, msg: dict[str, Any]) -> None:
        self._write((json.dumps(msg, separators=(",", ":"), default=str) + "\n").encode())

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _call(self, req_id: Any, fn: Handler, params: dict[str, Any]) -> None:
        try:
            result = await fn(params)
            if req_id is not None:
                self._send({"jsonrpc": "2.0", "id": req_id, "result": result})
        except RpcError as exc:
            if req_id is not None:
                err: dict[str, Any] = {"code": exc.code, "message": exc.message}
                if exc.data is not None:
                    err["data"] = exc.data
                self._send({"jsonrpc": "2.0", "id": req_id, "error": err})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("rpc method failed")
            if req_id is not None:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": INTERNAL, "message": "internal error"},
                    }
                )

    def handle_line(self, line: bytes | str) -> None:
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": PARSE_ERROR, "message": "parse error"},
                }
            )
            return
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": INVALID_REQUEST, "message": "invalid request"},
                }
            )
            return
        req_id = msg.get("id")
        params = msg.get("params") or {}
        fn = self.methods.get(msg["method"])
        if fn is None:
            if req_id is not None:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": NOT_FOUND, "message": "method not found"},
                    }
                )
            return
        if not isinstance(params, dict):
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": INVALID_PARAMS, "message": "params must be an object"},
                }
            )
            return
        task = asyncio.create_task(self._call(req_id, fn, params))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def serve(self, read_line: Callable[[], Awaitable[bytes]] | None = None) -> None:
        """Runs until stdin closes (Electron quit or crashed): then the sidecar exits too."""
        read = read_line or (lambda: asyncio.to_thread(sys.stdin.buffer.readline))
        while line := await read():
            if line.strip():
                self.handle_line(line)
        for task in list(self.tasks):
            task.cancel()
