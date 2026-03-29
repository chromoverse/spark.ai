"""
playback/tts_player.py

Plays TTS audio received from the server — but ONLY when the screen is locked.
When the screen is unlocked, Electron handles TTS playback.

Screen lock detection is platform-specific:
  Windows: query the session lock state via ctypes
  macOS:   check CGSessionCopyCurrentDictionary
  Linux:   check D-Bus screensaver / loginctl

Registers callbacks on socket_client to receive tts-start / tts-chunk / tts-end.
Buffers incoming audio chunks and plays them sequentially.
"""

import asyncio
import logging
import sys
import numpy as np
import sounddevice as sd

from config import settings

logger = logging.getLogger(__name__)

# TTS audio from ElevenLabs arrives as PCM bytes (typically 22050Hz or 44100Hz)
# The server should include samplerate in tts-start; we default to 22050.
DEFAULT_TTS_SAMPLERATE = 22050


class TtsPlayer:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._playing: bool = False
        self._current_samplerate: int = DEFAULT_TTS_SAMPLERATE
        self._task: asyncio.Task | None = None

    def register(self) -> None:
        """Register this player as the TTS callback on socket_client."""
        from stream.socket_client import socket_client
        socket_client.on_tts_start(self._on_tts_start)
        socket_client.on_tts_chunk(self._on_tts_chunk)
        socket_client.on_tts_end(self._on_tts_end)
        socket_client.on_tts_interrupt(self._on_tts_interrupt)
        logger.debug("✅ TtsPlayer registered on socket_client")

    async def start(self) -> None:
        """Start the background playback loop."""
        self._task = asyncio.create_task(self._playback_loop(), name="tts-playback")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Socket callbacks ──────────────────────────────────────────────────────

    async def _on_tts_start(self, data: dict) -> None:
        if not is_screen_locked():
            logger.debug("🖥️ Screen unlocked — Electron handles TTS, daemon silent")
            return
        self._current_samplerate = data.get("samplerate", DEFAULT_TTS_SAMPLERATE)
        logger.info("🔊 TTS starting (screen locked — daemon will play)")

    async def _on_tts_chunk(self, audio: bytes) -> None:
        if not is_screen_locked():
            return
        await self._queue.put(audio)

    async def _on_tts_end(self, data: dict) -> None:
        if not is_screen_locked():
            return
        await self._queue.put(None)  # sentinel — marks end of stream

    async def _on_tts_interrupt(self, data: dict) -> None:
        # Drain the queue and stop current playback
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            sd.stop()
        except Exception:
            pass
        logger.info("🔇 TTS interrupted")

    # ── Playback loop ─────────────────────────────────────────────────────────

    async def _playback_loop(self) -> None:
        """
        Continuously dequeues audio chunks and plays them via sounddevice.
        Runs as a background asyncio task.
        """
        loop = asyncio.get_event_loop()
        chunk_buffer: list[bytes] = []

        while True:
            try:
                chunk = await self._queue.get()
            except asyncio.CancelledError:
                break

            if chunk is None:
                # Stream ended — play everything buffered
                if chunk_buffer:
                    audio_bytes = b"".join(chunk_buffer)
                    chunk_buffer = []
                    await loop.run_in_executor(
                        None, _play_pcm_blocking, audio_bytes, self._current_samplerate
                    )
                self._playing = False
                continue

            chunk_buffer.append(chunk)
            self._playing = True

            # Play chunks as they arrive without waiting for all of them
            # (streaming playback — matches ElevenLabs chunk delivery)
            if len(chunk_buffer) >= 2:
                audio_bytes = b"".join(chunk_buffer)
                chunk_buffer = []
                await loop.run_in_executor(
                    None, _play_pcm_blocking, audio_bytes, self._current_samplerate
                )


def _play_pcm_blocking(pcm_bytes: bytes, samplerate: int) -> None:
    """Convert raw PCM bytes → float32 and play via sounddevice."""
    try:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio = audio * settings.TTS_VOLUME
        sd.play(audio, samplerate=samplerate)
        sd.wait()
    except Exception as exc:
        logger.warning(f"⚠️ TTS playback error: {exc}")


# ── Screen lock detection ─────────────────────────────────────────────────────

def is_screen_locked() -> bool:
    """
    Returns True if the screen is currently locked.
    Best-effort — returns False on error (safe default: Electron handles TTS).
    """
    try:
        if sys.platform == "win32":
            return _is_locked_windows()
        elif sys.platform == "darwin":
            return _is_locked_macos()
        else:
            return _is_locked_linux()
    except Exception as exc:
        logger.debug(f"Screen lock check failed: {exc}")
        return False


def _is_locked_windows() -> bool:
    import ctypes
    user32 = ctypes.windll.User32  # type: ignore[attr-defined]
    # GetForegroundWindow returns None when the lock screen is active
    hwnd = user32.GetForegroundWindow()
    if hwnd == 0:
        return True
    # More reliable: check if the workstation is locked
    # OpenInputDesktop fails on the lock screen
    hDesk = user32.OpenInputDesktop(0, False, 0x0100)
    if hDesk == 0:
        return True
    user32.CloseDesktop(hDesk)
    return False


def _is_locked_macos() -> bool:
    import subprocess
    result = subprocess.run(
        ["python3", "-c",
         "import Quartz; s = Quartz.CGSessionCopyCurrentDictionary(); "
         "print(s.get('CGSSessionScreenIsLocked', False))"],
        capture_output=True, text=True, timeout=1,
    )
    return result.stdout.strip().lower() == "true"


def _is_locked_linux() -> bool:
    import subprocess
    # Try loginctl first (systemd)
    try:
        result = subprocess.run(
            ["loginctl", "show-session", "self", "-p", "LockedHint"],
            capture_output=True, text=True, timeout=1,
        )
        return "yes" in result.stdout.lower()
    except FileNotFoundError:
        pass
    # Fallback: D-Bus screensaver
    try:
        result = subprocess.run(
            ["dbus-send", "--session", "--dest=org.gnome.ScreenSaver",
             "--type=method_call", "--print-reply",
             "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive"],
            capture_output=True, text=True, timeout=1,
        )
        return "true" in result.stdout.lower()
    except Exception:
        return False


# Module-level singleton
tts_player = TtsPlayer()