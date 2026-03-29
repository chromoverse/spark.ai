"""
stream/socket_client.py

Socket.IO client for the voice daemon.

Responsibilities:
  - Connect to server on boot (after /health passes)
  - Authenticate with DAEMON_SERVICE_TOKEN (not a user JWT)
  - Emit voice events: user-speech-started, user-speaking, user-stop-speaking, user-interrupt
  - Receive TTS events from server: tts-start, tts-chunk, tts-end, tts-interrupt
  - Route TTS events to playback/tts_player.py (only when screen is locked)
  - Auto-reconnect on drop (unlimited retries)

NOTE: The server's connect handler currently only accepts user JWTs.
      It needs a small addition to also accept DAEMON_SERVICE_TOKEN.
      See the comment block at the bottom of this file.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Any

import socketio

from config import settings

logger = logging.getLogger(__name__)

# Callback type that tts_player registers for incoming TTS audio
TtsChunkCallback = Callable[[bytes], Awaitable[None]]
TtsEventCallback = Callable[[dict], Awaitable[None]]


class DaemonSocketClient:
    def __init__(self) -> None:
        self._sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=settings.SOCKET_RECONNECT_ATTEMPTS,  # 0 = unlimited
            reconnection_delay=settings.SOCKET_RECONNECT_DELAY_S,
            reconnection_delay_max=30.0,
            logger=False,
            engineio_logger=False,
        )
        self._connected = False
        self._session_id: str | None = None

        # Callbacks registered by other modules
        self._on_tts_start:     TtsEventCallback | None = None
        self._on_tts_chunk:     TtsChunkCallback | None = None
        self._on_tts_end:       TtsEventCallback | None = None
        self._on_tts_interrupt: TtsEventCallback | None = None

        self._bind_events()

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to server. Blocks until connected or raises."""
        url = settings.SERVER_URL
        logger.info(f"🔌 Connecting daemon socket to {url}")
        await self._sio.connect(
            url,
            socketio_path="/socket.io",
            transports=["websocket", "polling"],
            auth={"token": settings.DAEMON_SERVICE_TOKEN, "client_type": "daemon"},
            wait=True,
        )

    async def disconnect(self) -> None:
        if self._sio.connected:
            await self._sio.disconnect()

    async def wait(self) -> None:
        """Block forever — keeps the asyncio event loop alive."""
        await self._sio.wait()

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Emit helpers — called by chunker / core ───────────────────────────────

    async def emit_speech_started(self, session_id: str) -> None:
        """Signal server to pre-load context before audio arrives."""
        if not self._connected:
            return
        await self._sio.emit("user-speech-started", {
            "sessionId": session_id,
            "timestamp": self._now(),
            "source": "daemon",
        })
        logger.debug(f"📤 user-speech-started  session={session_id[:8]}…")

    async def emit_speaking_chunk(
        self,
        pcm_buffer: bytes,
        session_id: str,
        seq: int,
    ) -> None:
        """Send a PCM chunk to the server."""
        if not self._connected:
            logger.warning("⚠️ Socket not connected — dropping audio chunk")
            return
        await self._sio.emit("user-speaking", {
            "audio": pcm_buffer,
            "mimeType": "audio/pcm;rate=16000",
            "sessionId": session_id,
            "seq": seq,
            "timestamp": self._now(),
            "source": "daemon",
        })
        if settings.LOG_AUDIO_PAYLOADS:
            logger.debug(f"📤 user-speaking chunk #{seq}  {len(pcm_buffer)}B  session={session_id[:8]}…")

    async def emit_stop_speaking(self, session_id: str) -> None:
        if not self._connected:
            return
        await self._sio.emit("user-stop-speaking", {
            "sessionId": session_id,
            "timestamp": self._now(),
            "source": "daemon",
        })
        logger.debug(f"📤 user-stop-speaking  session={session_id[:8]}…")

    async def emit_interrupt(self) -> None:
        if not self._connected:
            return
        await self._sio.emit("user-interrupt", {
            "timestamp": self._now(),
            "source": "daemon",
        })
        logger.debug("📤 user-interrupt")

    # ── TTS callback registration — called by tts_player ─────────────────────

    def on_tts_start(self, cb: TtsEventCallback) -> None:
        self._on_tts_start = cb

    def on_tts_chunk(self, cb: TtsChunkCallback) -> None:
        self._on_tts_chunk = cb

    def on_tts_end(self, cb: TtsEventCallback) -> None:
        self._on_tts_end = cb

    def on_tts_interrupt(self, cb: TtsEventCallback) -> None:
        self._on_tts_interrupt = cb

    # ── Socket.IO event bindings ──────────────────────────────────────────────

    def _bind_events(self) -> None:
        sio = self._sio

        @sio.event
        async def connect():  # type: ignore[no-untyped-def]
            self._connected = True
            logger.info("✅ Daemon socket connected")

        @sio.event
        async def disconnect(reason: str):  # type: ignore[no-untyped-def]
            self._connected = False
            logger.warning(f"🔌 Daemon socket disconnected: {reason}")

        @sio.event
        async def connect_error(data: Any):  # type: ignore[no-untyped-def]
            self._connected = False
            logger.error(f"❌ Daemon socket connect error: {data}")

        # TTS events from server — daemon only plays these when screen is locked.
        # Screen-lock detection is the responsibility of tts_player.py.
        @sio.on("tts-start")
        async def on_tts_start(data: dict):  # type: ignore[no-untyped-def]
            logger.debug("🔊 tts-start received")
            if self._on_tts_start:
                await self._on_tts_start(data)

        @sio.on("tts-chunk")
        async def on_tts_chunk(data: dict):  # type: ignore[no-untyped-def]
            audio: bytes = data.get("audio", b"")
            if self._on_tts_chunk and audio:
                await self._on_tts_chunk(audio)

        @sio.on("tts-end")
        async def on_tts_end(data: dict):  # type: ignore[no-untyped-def]
            logger.debug("🔊 tts-end received")
            if self._on_tts_end:
                await self._on_tts_end(data)

        @sio.on("tts-interrupt")
        async def on_tts_interrupt(data: dict):  # type: ignore[no-untyped-def]
            logger.debug("🔇 tts-interrupt received")
            if self._on_tts_interrupt:
                await self._on_tts_interrupt(data)

    @staticmethod
    def _now() -> int:
        import time
        return int(time.time() * 1000)


# Module-level singleton
socket_client = DaemonSocketClient()


# ─────────────────────────────────────────────────────────────────────────────
# SERVER-SIDE CHANGE NEEDED — add this to app/socket/server.py connect handler:
# ─────────────────────────────────────────────────────────────────────────────
#
#   DAEMON_SERVICE_TOKEN = os.environ.get("DAEMON_SERVICE_TOKEN", "")
#
#   @sio.event
#   async def connect(sid, environ, auth):
#       token = auth.get("token", "")
#       client_type = auth.get("client_type", "user")
#
#       # ── Daemon auth (static service token) ───────────────────────────────
#       if client_type == "daemon":
#           if not DAEMON_SERVICE_TOKEN:
#               raise ConnectionRefusedError("Daemon service token not configured")
#           if token != DAEMON_SERVICE_TOKEN:
#               raise ConnectionRefusedError("Invalid daemon service token")
#           await sio.save_session(sid, {
#               "user_id": "__daemon__",
#               "client_type": "daemon",
#               "authenticated": True,
#           })
#           logger.info(f"🤖 Daemon connected with sid {sid}")
#           return True
#
#       # ── Normal user JWT auth (existing logic) ─────────────────────────────
#       ... (rest of existing connect handler unchanged)
# ─────────────────────────────────────────────────────────────────────────────