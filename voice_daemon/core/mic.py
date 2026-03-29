"""
core/mic.py

Exclusive microphone capture using sounddevice.
Runs a continuous InputStream at 16kHz mono float32.

On every audio frame:
  - If IDLE:      forwards to wake_word.py for detection
  - If STREAMING: forwards to chunker.py for accumulation + sending

The mic is opened ONCE at startup and never closed (daemon owns the mic).
Device index is configurable via MIC_DEVICE_INDEX env var.
"""

import asyncio
import logging
import numpy as np
import sounddevice as sd

from config import settings
from core.state import fsm, State

logger = logging.getLogger(__name__)

# Samples per frame — derived from CHUNK_MS and SAMPLE_RATE
FRAME_SAMPLES = int(settings.SAMPLE_RATE * settings.CHUNK_MS / 1000)  # 320 @ 16kHz/20ms


class MicCapture:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Open the mic stream. Must be called from the main thread before
        the asyncio loop starts (sounddevice callbacks run in a C thread).
        """
        self._loop = loop

        device = settings.MIC_DEVICE_INDEX  # None = system default
        if device is not None:
            logger.info(f"🎤 Opening mic device index {device}")
        else:
            logger.info("🎤 Opening default mic device")

        self._stream = sd.InputStream(
            samplerate=settings.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            device=device,
            callback=self._sd_callback,
            latency="low",
        )
        self._stream.start()
        logger.info(
            f"✅ Mic stream open — {settings.SAMPLE_RATE}Hz / "
            f"{settings.CHUNK_MS}ms frames / {FRAME_SAMPLES} samples per frame"
        )

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("🛑 Mic stream closed")

    def _sd_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """
        Called by sounddevice in a C thread on every audio frame.
        Must be fast and non-blocking — dispatch to asyncio via call_soon_threadsafe.
        """
        if status:
            logger.warning(f"⚠️ Mic status: {status}")

        # Copy the frame — indata is reused by sounddevice after return
        frame = indata[:, 0].copy()  # mono: drop channel dim

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        state = fsm.current()

        if state == State.IDLE:
            # Route to wake word detector
            asyncio.run_coroutine_threadsafe(_route_to_wake_word(frame), loop)
        elif state == State.STREAMING:
            # Route to chunker
            asyncio.run_coroutine_threadsafe(_route_to_chunker(frame), loop)
        # WAKE / LISTENING / PROCESSING — drop frames (not needed)


async def _route_to_wake_word(frame: np.ndarray) -> None:
    from core.wake_word import wake_word_detector
    await wake_word_detector.process_frame(frame)


async def _route_to_chunker(frame: np.ndarray) -> None:
    from stream.chunker import chunker
    await chunker.push_frame(frame)


# Module-level singleton
mic = MicCapture()