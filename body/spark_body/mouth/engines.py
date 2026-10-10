"""TTS engine contract and the engines themselves (REDESIGN §18). An engine streams encoded audio
chunks; the renderer plays them (Chromium decodes MP3/WAV, so the body needs no decoder)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import threading
import urllib.error
import urllib.request
import wave
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from spark_body import models

# PERSONA §5 tone → Groq Orpheus vocal direction. "chill" is the default voice: no tag.
ORPHEUS_DIRECTIONS = {
    "cheerful": "cheerful",
    "calm": "calm",
    "serious": "serious",
    "excited": "excited",
    "whisper": "whisper",
}
_TAGS = re.compile(r"\[[a-z_ ]{2,20}\]\s*", re.IGNORECASE)

STANDARD_SENTENCE = "Sure, I can help with that, it should only take a moment."  # 12 words


class TtsEngine(Protocol):
    name: str
    expressive: bool  # takes vocal-direction tags (Orpheus); others get them stripped
    mime: str

    def available(self) -> bool:
        """Dependencies installed and keys present. False → excluded before benchmarking."""
        ...

    def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        """`text` is already prepared (tone handled); yields encoded audio chunks."""
        ...


def wav(pcm16: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def threads() -> int:
    """sherpa-onnx threads per model: half the cores, at most 4 (more gained nothing)."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def prepare(engine: TtsEngine, text: str, tone: str | None) -> str:
    """FT5: tone tags become vocal directions on expressive engines and vanish elsewhere."""
    clean = _TAGS.sub("", text).strip()
    if engine.expressive and tone in ORPHEUS_DIRECTIONS:
        return f"[{ORPHEUS_DIRECTIONS[tone]}] {clean}"
    return clean


class EdgeTts:
    """Microsoft Edge read-aloud voices via `edge-tts` (free, natural, unofficial). Runs on the
    device because datacenter IPs get blocked (RESEARCH §5)."""

    name = "edge-tts"
    expressive = False
    mime = "audio/mpeg"

    def __init__(self, voice: str = "en-US-AvaMultilingualNeural") -> None:
        self.voice = voice

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        import edge_tts

        stream = edge_tts.Communicate(text, self.voice).stream()
        try:
            async for chunk in stream:
                if chunk.get("type") == "audio" and chunk.get("data"):
                    yield chunk["data"]
        finally:
            # Probes and barge-in stop early: close edge-tts's generator so its aiohttp session
            # closes too (otherwise "Unclosed client session" and a pending task leak).
            await stream.aclose()


@dataclass
class BrainLink:
    """Where the brain is and a current access token. Electron main sets it (`auth.set`) and
    refreshes it before it expires; it lives only in memory."""

    url: str = ""
    token: str = ""


class ProxyError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"brain proxy {status}")
        self.status = status


class OrpheusProxy:
    """Groq Orpheus through the brain's proxy (platform keys stay in the brain): the most
    expressive voice, ~100 free clips a day, so it leads the plan while it fits and has quota."""

    name = "groq-orpheus"
    expressive = True
    mime = "audio/wav"

    def __init__(self, link: BrainLink, voice: str = "daniel") -> None:
        self.link = link
        self.voice = voice

    def available(self) -> bool:
        return bool(self.link.url and self.link.token)

    def _post(self, text: str) -> bytes:
        req = urllib.request.Request(  # noqa: S310 (the brain URL from Electron main)
            f"{self.link.url}/v2/proxy/tts",
            data=json.dumps({"text": text[:200], "voice": self.voice}).encode(),
            headers={
                "Authorization": f"Bearer {self.link.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310
                data: bytes = r.read()
                return data
        except urllib.error.HTTPError as exc:
            raise ProxyError(exc.code) from None

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        # `text` already carries the vocal direction (prepare); the proxy gets no extra tone
        yield await asyncio.to_thread(self._post, text)


# One local voice runs at a time, across voices too: they share espeak-ng's global state. Taken on
# the worker thread, not the event loop: a timed-out (cancelled) call's native work keeps running,
# and a second load racing it hung the sidecar.
_NATIVE = threading.Lock()


class LocalTts:
    """A voice from the model catalog (spark_body/models.py), synthesized on this device's CPU by
    sherpa-onnx. Loads on first use (or warm())."""

    expressive = False
    mime = "audio/wav"

    def __init__(self, model: models.Model, root: Path) -> None:
        self.name = model.name
        self.model = model
        self.folder = root / model.name
        self._tts: Any = None

    def available(self) -> bool:
        return models.runtime() and models.installed(self.folder.parent, self.name) is not None

    def _load(self) -> Any:
        import sherpa_onnx as so

        d, kind = self.folder, self.model.kind
        cfg = so.OfflineTtsModelConfig(num_threads=threads(), provider="cpu")
        if kind == "vits":
            cfg.vits = so.OfflineTtsVitsModelConfig(
                model=models.one(d, "*.onnx"),
                tokens=str(d / "tokens.txt"),
                data_dir=str(d / "espeak-ng-data"),
            )
        elif kind == "kokoro":
            cfg.kokoro = so.OfflineTtsKokoroModelConfig(
                model=models.one(d, "model*.onnx"),
                voices=str(d / "voices.bin"),
                tokens=str(d / "tokens.txt"),
                data_dir=str(d / "espeak-ng-data"),
                lexicon=str(d / "lexicon-us-en.txt"),
                dict_dir=str(d / "dict"),
            )
        else:
            raise ValueError(f"{self.name}: not a TTS model")
        return so.OfflineTts(so.OfflineTtsConfig(model=cfg, max_num_sentences=1))

    def _generate(self, text: str) -> bytes:
        import numpy as np

        with _NATIVE:
            if self._tts is None:
                self._tts = self._load()
            audio = self._tts.generate(text, sid=self.model.sid, speed=1.0)
        samples = np.clip(np.asarray(audio.samples, dtype=np.float32), -1.0, 1.0)
        return wav((samples * 32767).astype("<i2").tobytes(), audio.sample_rate)

    async def warm(self) -> None:
        """Load and run once, so neither the benchmark nor the first reply pays for it (the
        first call took ~1.5 s on the owner's laptop against ~140 ms after)."""
        await asyncio.to_thread(self._generate, "Ready.")

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        clip = await asyncio.to_thread(self._generate, text)
        if len(clip) > 44:  # more than a WAV header
            yield clip
