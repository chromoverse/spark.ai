"""
stream/chunker.py

Converts a continuous Float32 mic stream into 16-bit PCM chunks
and forwards them to socket_client.

Called by core/mic.py on every audio frame during STREAMING state.
The chunker accumulates frames until STREAM_CHUNK_SAMPLES is reached,
then flushes — matching the Electron AudioInput behaviour (~2s chunks).

On speech end, flush() is called explicitly to drain any remainder
before user-stop-speaking is emitted.
"""

import uuid
import time
import logging
import numpy as np

from config import settings

logger = logging.getLogger(__name__)

# How many samples to accumulate before sending a chunk (~2s at 16kHz)
STREAM_CHUNK_SAMPLES = settings.SAMPLE_RATE * 2     # 32 000
MIN_PCM_SAMPLES      = settings.SAMPLE_RATE // 10   # 1 600  (~100ms — ignore tiny clips)


def _float32_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] → int16 PCM bytes."""
    clamped = np.clip(audio, -1.0, 1.0)
    pcm = np.where(clamped < 0, clamped * 32768, clamped * 32767).astype(np.int16)
    return pcm.tobytes()


class AudioChunker:
    def __init__(self) -> None:
        self._session_id: str | None = None
        self._seq: int = 0
        self._accumulator: list[np.ndarray] = []
        self._accumulated_samples: int = 0

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def begin_session(self) -> str:
        """Call on wake → STREAMING transition. Returns new session_id."""
        self._session_id = str(uuid.uuid4())
        self._seq = 0
        self._accumulator = []
        self._accumulated_samples = 0
        logger.debug(f"🎙️ Chunker session started: {self._session_id[:8]}…")
        return self._session_id

    def end_session(self) -> str | None:
        """Returns the session_id that just ended (for emit_stop_speaking)."""
        sid = self._session_id
        self._session_id = None
        self._accumulator = []
        self._accumulated_samples = 0
        return sid

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── Frame ingestion ───────────────────────────────────────────────────────

    async def push_frame(self, frame: np.ndarray) -> None:
        """
        Called on every mic capture frame while in STREAMING state.
        Accumulates frames; flushes when threshold is reached.
        """
        if self._session_id is None:
            return

        self._accumulator.append(frame)
        self._accumulated_samples += len(frame)

        if self._accumulated_samples >= STREAM_CHUNK_SAMPLES:
            await self._flush()

    async def flush(self) -> None:
        """Drain remaining frames — call just before end_session."""
        await self._flush(force=True)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _flush(self, force: bool = False) -> None:
        from stream.socket_client import socket_client  # avoid circular at module level

        if not self._accumulator:
            return
        if not force and self._accumulated_samples < MIN_PCM_SAMPLES:
            return
        if not self._session_id:
            return

        merged = np.concatenate(self._accumulator)
        pcm_bytes = _float32_to_pcm16(merged)

        seq = self._seq
        self._seq += 1
        self._accumulator = []
        self._accumulated_samples = 0

        await socket_client.emit_speaking_chunk(
            pcm_buffer=pcm_bytes,
            session_id=self._session_id,
            seq=seq,
        )
        logger.debug(f"📤 Chunk #{seq}  {len(pcm_bytes)}B  session={self._session_id[:8]}…")


# Module-level singleton
chunker = AudioChunker()