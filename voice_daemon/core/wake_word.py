"""
core/wake_word.py

Wake word detection using openwakeword.
Receives raw float32 audio frames from core/mic.py while in IDLE state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import numpy as np

from config import settings
from core.state import State, fsm

logger = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self) -> None:
        self._model = None
        self._last_trigger_ts: float = 0.0

    def load(self) -> None:
        """
        Load all configured Spark wake word models.
        """
        missing_models = self._missing_model_paths()
        if missing_models:
            missing_list = "\n".join(f"  - {path}" for path in missing_models)
            raise RuntimeError(
                "[voice_daemon] Missing Spark wake word model file(s).\n"
                f"{missing_list}\n"
                f"Expected custom model assets under: {settings.MODELS_DIR}"
            )

        from openwakeword.model import Model

        logger.info(
            "⏳ Loading wake word models for phrases: %s",
            ", ".join(settings.WAKE_WORD_PHRASES),
        )

        try:
            self._model = Model(
                wakeword_models=list(settings.WAKE_WORD_MODEL_PATHS),
                inference_framework="onnx",
            )
            logger.info(
                "✅ Wake word models loaded: %s",
                ", ".join(Path(path).name for path in settings.WAKE_WORD_MODEL_PATHS),
            )
        except Exception as exc:
            logger.error(
                "❌ Failed to load wake word models for phrases %s: %s\n"
                "   Check that the Spark ONNX model files are valid and readable.",
                ", ".join(settings.WAKE_WORD_PHRASES),
                exc,
            )
            raise

    def _missing_model_paths(self) -> list[str]:
        return [
            path for path in settings.WAKE_WORD_MODEL_PATHS if not Path(path).is_file()
        ]

    async def process_frame(self, frame: np.ndarray) -> None:
        """
        Feed one audio frame to openwakeword.
        Called from mic._sd_callback via asyncio — must not block.
        """
        if self._model is None:
            return

        now = time.monotonic()
        if (now - self._last_trigger_ts) < settings.WAKE_WORD_COOLDOWN_S:
            return

        pcm16 = (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)
        prediction = self._model.predict(pcm16)

        label, score = self._get_best_prediction(prediction)
        if score >= settings.WAKE_WORD_THRESHOLD:
            self._last_trigger_ts = now
            spoken_phrase = settings.WAKE_WORD_PHRASE_BY_MODEL.get(label, label)
            logger.info("🔔 Wake phrase detected: %s (score=%.3f)", spoken_phrase, score)
            await self._on_wake()

    def _get_best_prediction(self, prediction: dict[str, object]) -> tuple[str, float]:
        if not prediction:
            return "", 0.0

        best_label = ""
        best_score = 0.0

        for raw_label, raw_scores in prediction.items():
            score = self._score_value(raw_scores)
            normalized_label = Path(str(raw_label)).stem
            if score > best_score:
                best_label = normalized_label
                best_score = score

        return best_label, best_score

    def _score_value(self, value: object) -> float:
        if isinstance(value, (list, tuple, np.ndarray)):
            flattened = [float(item) for item in value]
            return max(flattened) if flattened else 0.0
        return float(value)

    async def _on_wake(self) -> None:
        if fsm.is_busy():
            logger.debug("⏸️ Wake word ignored — daemon is busy")
            return

        ok = await fsm.transition(State.WAKE)
        if not ok:
            return

        from playback.ding import play_ding

        await play_ding()
        await fsm.transition(State.LISTENING)
        logger.info("👂 Listening…")


wake_word_detector = WakeWordDetector()
