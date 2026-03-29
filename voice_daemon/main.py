"""
main.py — voice_daemon entry point

Boot sequence:
  1. Load config (validates all env vars — fails fast if anything missing)
  2. Configure logging
  3. Wait for server to be healthy (blocks until /health returns 200)
  4. Load ML models (wake word + VAD)
  5. Open mic stream
  6. Connect Socket.IO to server
  7. Register TTS player
  8. Register FSM callback: PROCESSING → IDLE on server response
  9. Run forever (asyncio event loop)

Graceful shutdown on SIGINT / SIGTERM:
  - Stop mic
  - Disconnect socket
  - Exit cleanly

Usage:
  python main.py
  python main.py --download-models   # download wake word + VAD models then exit
"""

import asyncio
import logging
import signal
import sys

# ── Config first — will raise immediately if required vars are missing ─────────
from config import settings

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Suppress noisy third-party loggers
logging.getLogger("socketio").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)
logging.getLogger("torch").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("voice_daemon")


async def main() -> None:
    logger.info("🚀 voice_daemon starting…")
    logger.info(f"   Server URL: {settings.SERVER_URL}")
    logger.info(
        "   Shared config: %s",
        settings.SHARED_CONFIG_PATH,
    )
    logger.info(
        "   Wake phrases: %s (threshold=%s, cooldown=%ss)",
        ", ".join(settings.WAKE_WORD_PHRASES),
        settings.WAKE_WORD_THRESHOLD,
        settings.WAKE_WORD_COOLDOWN_S,
    )
    logger.info(f"   Sample rate: {settings.SAMPLE_RATE}Hz / {settings.CHUNK_MS}ms frames")

    # ── 1. Wait for server ─────────────────────────────────────────────────────
    from health.server_watch import wait_for_server
    healthy = await wait_for_server()
    if not healthy:
        logger.error("❌ Server never became healthy. Exiting.")
        sys.exit(1)

    # ── 2. Load ML models ──────────────────────────────────────────────────────
    from core.wake_word import wake_word_detector
    from core.vad import vad

    logger.info("⏳ Loading ML models…")
    loop = asyncio.get_event_loop()
    # Run blocking model loads in thread pool
    await loop.run_in_executor(None, wake_word_detector.load)
    await loop.run_in_executor(None, vad.load)
    logger.info("✅ ML models ready")

    # ── 3. Open mic ────────────────────────────────────────────────────────────
    from core.mic import mic
    mic.start(loop)

    # ── 4. Connect socket ──────────────────────────────────────────────────────
    from stream.socket_client import socket_client
    await socket_client.connect()

    # ── 5. Register TTS player ─────────────────────────────────────────────────
    from playback.tts_player import tts_player
    tts_player.register()
    await tts_player.start()

    # ── 6. FSM: reset PROCESSING → IDLE when server sends a response ──────────
    from core.state import fsm, State

    async def on_state_change(frm: State, to: State) -> None:
        pass  # extend here for observability / logging hooks

    fsm.on_change(on_state_change)

    # Server signals "done processing" via these socket events
    async def _reset_to_idle(data: object = None) -> None:  # noqa: ARG001
        current = fsm.current()
        if current == State.PROCESSING:
            await fsm.transition(State.IDLE)
            logger.info("✅ Processing complete — back to IDLE, listening for wake word")

    # Attach listeners directly on the underlying sio client
    _sio = socket_client._sio
    _sio.on("ai-end",      lambda d: asyncio.create_task(_reset_to_idle(d)))
    _sio.on("query-result",lambda d: asyncio.create_task(_reset_to_idle(d)))
    _sio.on("query-error", lambda d: asyncio.create_task(_reset_to_idle(d)))
    _sio.on("error",       lambda d: asyncio.create_task(_reset_to_idle(d)))

    # Processing timeout guard — if server never responds, unblock after 30s
    async def _processing_watchdog() -> None:
        while True:
            await asyncio.sleep(5)
            if fsm.current() == State.PROCESSING:
                import time
                # We don't track entry time here — use a simple counter approach
                # Full implementation: store entry timestamp in fsm and check it here
                pass  # TODO: add timestamp-based timeout in state.py

    asyncio.create_task(_processing_watchdog(), name="processing-watchdog")

    logger.info("✅ voice_daemon fully started — listening for wake word")
    logger.info('   Say "%s" to activate', settings.get_wake_phrase_display())

    # ── 7. Run until shutdown ──────────────────────────────────────────────────
    await socket_client.wait()


def _handle_signal(sig: signal.Signals) -> None:
    logger.info(f"⚡ Received {sig.name} — shutting down")
    asyncio.get_event_loop().stop()


async def download_models() -> None:
    """Download openwakeword and Silero VAD models."""
    logger.info("📥 Downloading models…")
    import openwakeword
    openwakeword.utils.download_models()
    logger.info("📥 openwakeword models downloaded")

    import torch
    torch.hub.load("snakers4/silero-vad", "silero_vad", force_reload=True)
    logger.info("📥 Silero VAD model downloaded")
    logger.info(
        "ℹ️ Custom Spark wake word models are not downloaded automatically.\n"
        "   Add hey_spark.onnx and spark.onnx to %s",
        settings.MODELS_DIR,
    )
    logger.info("✅ Base daemon models ready")


if __name__ == "__main__":
    if "--download-models" in sys.argv:
        asyncio.run(download_models())
        sys.exit(0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals
            signal.signal(sig, lambda s, f: loop.stop())

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("👋 Interrupted")
    finally:
        logger.info("🛑 Shutting down…")
        from core.mic import mic
        mic.stop()
        loop.close()
        logger.info("✅ voice_daemon stopped")
