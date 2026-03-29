"""
core/vad.py

Silero VAD — detects speech start and speech end while in LISTENING state.

Unlike the Electron implementation (which uses @ricky0123/vad-web), this is
the Python Silero VAD running natively via PyTorch.

Flow:
  LISTENING state → VAD receives frames from mic
  Speech start detected → emit user-speech-started, LISTENING → STREAMING
  Speech end detected   → flush chunker, emit user-stop-speaking, STREAMING → PROCESSING
  Processing done       → PROCESSING → IDLE (triggered by FSM callback in main.py)

Silero VAD operates on 512-sample windows at 16kHz (32ms per window).
We accumulate mic frames until we have enough for one VAD window.
"""

import asyncio
import logging
import numpy as np

from config import settings
from core.state import fsm, State

logger = logging.getLogger(__name__)

# Silero VAD requires exactly 512 samples per inference at 16kHz
VAD_WINDOW_SAMPLES = 512

# Silence timeout — if VAD stays negative for this long after LISTENING, reset to IDLE
SILENCE_TIMEOUT_S = 8.0


class SileroVAD:
    def __init__(self) -> None:
        self._model = None
        self._utils = None
        self._frame_buffer: list[np.ndarray] = []
        self._buffered_samples: int = 0

        # Rolling speech probability tracking
        self._consecutive_positive: int = 0
        self._consecutive_negative: int = 0
        self._in_speech: bool = False

        # Silence timeout tracking
        self._listening_since: float | None = None

    def load(self) -> None:
        """Load Silero VAD model. Call once at startup (~500ms)."""
        import torch
        logger.info("⏳ Loading Silero VAD model…")
        self._model, self._utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        self._model.eval()
        logger.info("✅ Silero VAD model loaded")

    async def process_frame(self, frame: np.ndarray) -> None:
        """
        Called by mic.py when FSM is in LISTENING or STREAMING state.
        Accumulates frames into VAD windows and runs inference.
        """
        if self._model is None:
            return

        state = fsm.current()
        if state not in (State.LISTENING, State.STREAMING):
            return

        # Track how long we've been listening without speech
        if state == State.LISTENING and self._listening_since is None:
            import time
            self._listening_since = time.monotonic()

        self._frame_buffer.append(frame)
        self._buffered_samples += len(frame)

        # Process full VAD windows
        while self._buffered_samples >= VAD_WINDOW_SAMPLES:
            await self._run_vad_window()

        # Silence timeout — reset to IDLE if no speech starts
        if state == State.LISTENING and self._listening_since is not None:
            import time
            elapsed = time.monotonic() - self._listening_since
            if elapsed > SILENCE_TIMEOUT_S:
                logger.info("⏱️ Silence timeout — returning to IDLE")
                self._reset_tracking()
                await fsm.transition(State.IDLE)

    async def _run_vad_window(self) -> None:
        import torch

        # Consume exactly VAD_WINDOW_SAMPLES from buffer
        needed = VAD_WINDOW_SAMPLES
        consumed: list[np.ndarray] = []
        remaining_needed = needed

        for chunk in self._frame_buffer:
            if remaining_needed <= 0:
                break
            take = min(len(chunk), remaining_needed)
            consumed.append(chunk[:take])
            remaining_needed -= take

        window = np.concatenate(consumed)[:needed]

        # Rebuild buffer without the consumed samples
        all_samples = np.concatenate(self._frame_buffer)
        leftover = all_samples[needed:]
        self._frame_buffer = [leftover] if len(leftover) > 0 else []
        self._buffered_samples = len(leftover)

        # Run Silero inference
        tensor = torch.from_numpy(window).unsqueeze(0)
        with torch.no_grad():
            speech_prob: float = self._model(tensor, settings.SAMPLE_RATE).item()

        await self._handle_probability(speech_prob)

    async def _handle_probability(self, prob: float) -> None:
        state = fsm.current()

        if prob >= settings.VAD_POSITIVE_SPEECH_THRESHOLD:
            self._consecutive_positive += 1
            self._consecutive_negative = 0

            # Speech start: was LISTENING, enough positive frames
            if state == State.LISTENING and not self._in_speech:
                min_positive_frames = max(1, settings.VAD_MIN_SPEECH_MS // 32)
                if self._consecutive_positive >= min_positive_frames:
                    self._in_speech = True
                    self._listening_since = None
                    await self._on_speech_start()

        elif prob < settings.VAD_NEGATIVE_SPEECH_THRESHOLD:
            self._consecutive_negative += 1
            self._consecutive_positive = 0

            # Speech end: was STREAMING, enough negative frames
            if state == State.STREAMING and self._in_speech:
                redemption_frames = max(1, settings.VAD_REDEMPTION_MS // 32)
                if self._consecutive_negative >= redemption_frames:
                    self._in_speech = False
                    await self._on_speech_end()

    async def _on_speech_start(self) -> None:
        from stream.socket_client import socket_client
        from stream.chunker import chunker

        ok = await fsm.transition(State.STREAMING)
        if not ok:
            return

        session_id = chunker.begin_session()
        await socket_client.emit_speech_started(session_id)
        logger.info(f"🎤 Speech started — session {session_id[:8]}…")

    async def _on_speech_end(self) -> None:
        from stream.socket_client import socket_client
        from stream.chunker import chunker

        # Flush remaining audio before signalling stop
        await chunker.flush()
        session_id = chunker.end_session()

        if session_id:
            await socket_client.emit_stop_speaking(session_id)
            logger.info(f"🛑 Speech ended — session {session_id[:8]}… finalized")

        await fsm.transition(State.PROCESSING)
        self._reset_tracking()

    def _reset_tracking(self) -> None:
        self._consecutive_positive = 0
        self._consecutive_negative = 0
        self._in_speech = False
        self._frame_buffer = []
        self._buffered_samples = 0
        self._listening_since = None


# Module-level singleton
vad = SileroVAD()