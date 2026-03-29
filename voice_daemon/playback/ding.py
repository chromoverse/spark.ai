"""
playback/ding.py

Plays ding.wav when a wake word is detected.
Blocking playback — wake_word.py awaits this before transitioning to LISTENING.
Uses sounddevice for system-level audio (works on lock screen).
"""

import asyncio
import logging
import os
import numpy as np
import sounddevice as sd

from config import settings

logger = logging.getLogger(__name__)

# Cache the wav data — loaded once, played many times
_ding_data: np.ndarray | None = None
_ding_samplerate: int = 44100


def _load_ding() -> tuple[np.ndarray, int]:
    """Load ding.wav into memory. Returns (audio_array, samplerate)."""
    global _ding_data, _ding_samplerate

    if _ding_data is not None:
        return _ding_data, _ding_samplerate

    path = settings.DING_WAV_PATH
    if not os.path.isfile(path):
        logger.warning(
            f"⚠️ ding.wav not found at: {path}\n"
            f"   Wake word will fire silently. Add assets/ding.wav to fix this."
        )
        _ding_data = np.zeros(1000, dtype=np.float32)
        _ding_samplerate = 44100
        return _ding_data, _ding_samplerate

    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=False)
        if data.ndim == 2:
            data = data.mean(axis=1)  # stereo → mono
        _ding_data = data * settings.DING_VOLUME
        _ding_samplerate = sr
        logger.info(f"✅ ding.wav loaded — {len(data)/sr:.2f}s @ {sr}Hz")
        return _ding_data, _ding_samplerate
    except Exception as exc:
        logger.error(f"❌ Failed to load ding.wav: {exc}")
        _ding_data = np.zeros(1000, dtype=np.float32)
        _ding_samplerate = 44100
        return _ding_data, _ding_samplerate


async def play_ding() -> None:
    """
    Play ding.wav and block until playback is complete.
    Runs sd.play/wait in a thread so it doesn't block the asyncio event loop.
    """
    data, sr = _load_ding()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _play_blocking, data, sr)


def _play_blocking(data: np.ndarray, samplerate: int) -> None:
    try:
        sd.play(data, samplerate=samplerate)
        sd.wait()
    except Exception as exc:
        logger.warning(f"⚠️ ding.wav playback failed: {exc}")