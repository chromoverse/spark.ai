"""STT engine contract (REDESIGN §18): on-device model first, Groq Whisper through the brain's
proxy as the cloud fallback. Engines land with their fitness probes; the plan stays empty until
one passes on this device."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from spark_body import models
from spark_body.mouth.engines import BrainLink, ProxyError, threads, wav


@dataclass(frozen=True)
class Transcript:
    text: str
    lang: str = "en"
    confidence: float | None = None


class SttEngine(Protocol):
    name: str
    on_device: bool  # False → audio leaves the device (RULES §9: only when the plan picks it)

    def available(self) -> bool: ...

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript: ...


def floats(pcm16: bytes) -> Any:
    import numpy as np

    return np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0


# What Whisper says for noise or breath with no words (owner's mic test: "foreign"). Only whole
# transcripts that are exactly one of these are dropped.
HALLUCINATIONS = frozenset(
    {
        "foreign",
        "you",
        "thanks for watching",
        "thank you for watching",
        "please subscribe",
        "subtitles by the amara org community",
    }
)


def hallucinated(text: str) -> bool:
    return " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split()) in HALLUCINATIONS


class WhisperProxy:
    """Groq Whisper through the brain's proxy: the cloud fallback (§18). Audio leaves the
    device only when this engine is first in the plan (RULES §9)."""

    name = "groq-whisper"
    on_device = False

    def __init__(self, link: BrainLink, lang: str = "en") -> None:
        self.link = link
        self.lang = lang

    def available(self) -> bool:
        return bool(self.link.url and self.link.token)

    def _post(self, clip: bytes) -> dict[str, object]:
        req = urllib.request.Request(  # noqa: S310 (the brain URL from Electron main)
            f"{self.link.url}/v2/proxy/stt?lang={self.lang}",
            data=clip,
            headers={"Authorization": f"Bearer {self.link.token}", "Content-Type": "audio/wav"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                body: dict[str, object] = json.loads(r.read())
                return body
        except urllib.error.HTTPError as exc:
            raise ProxyError(exc.code) from None

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        body = await asyncio.to_thread(self._post, wav(pcm16, sample_rate))
        data = body.get("data")
        text = str(data.get("text", "")) if isinstance(data, dict) else ""
        return Transcript("" if hallucinated(text) else text.strip(), self.lang)


class LocalStt:
    """An on-device model from the catalog (spark_body/models.py) via sherpa-onnx: audio never
    leaves the device. English only for now; other languages go to Groq Whisper."""

    on_device = True

    def __init__(self, model: models.Model, root: Path) -> None:
        self.name = model.name
        self.model = model
        self.folder = root / model.name
        self._rec: Any = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return models.runtime() and models.installed(self.folder.parent, self.name) is not None

    def _load(self) -> Any:
        import sherpa_onnx as so

        d, n = self.folder, threads()
        if self.model.kind == "moonshine":
            return so.OfflineRecognizer.from_moonshine(
                preprocessor=models.one(d, "preprocess*.onnx"),
                encoder=models.one(d, "encode*.onnx"),
                uncached_decoder=models.one(d, "uncached_decode*.onnx"),
                cached_decoder=models.one(d, "cached_decode*.onnx"),
                tokens=str(d / "tokens.txt"),
                num_threads=n,
            )
        if self.model.kind == "nemo_transducer":
            return so.OfflineRecognizer.from_transducer(
                encoder=models.one(d, "encoder*.onnx"),
                decoder=models.one(d, "decoder*.onnx"),
                joiner=models.one(d, "joiner*.onnx"),
                tokens=str(d / "tokens.txt"),
                num_threads=n,
                model_type="nemo_transducer",
            )
        raise ValueError(f"{self.name}: not an STT model")

    def _decode(self, pcm16: bytes, sample_rate: int) -> str:
        with self._lock:  # on the worker thread: see mouth.engines._NATIVE
            if self._rec is None:
                self._rec = self._load()
            stream = self._rec.create_stream()
            stream.accept_waveform(sample_rate, floats(pcm16))
            self._rec.decode_stream(stream)
            return str(stream.result.text).strip()

    async def warm(self) -> None:
        """Load and run once on silence: the first call pays ~1.3 s of setup."""
        await asyncio.to_thread(self._decode, b"\x00\x00" * 8000, 16000)

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        text = await asyncio.to_thread(self._decode, pcm16, sample_rate)
        return Transcript(text, "en")
