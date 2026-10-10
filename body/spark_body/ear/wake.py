"""Wake word (REDESIGN §4.1): "Hey Spark" spotted on the device, with no custom model to train.
sherpa-onnx's open-vocabulary keyword spotter takes the phrase as subword tokens, so changing or
adding a phrase is a line below. Every endpointed utterance is checked before STT runs; audio
without the wake word is dropped on the device and never transcribed or sent anywhere.

Measured on synthetic clips (Piper, 3 voices, light noise): 11/12 wake phrases caught, 0 false
alarms on 15 near-misses ("hey Mark", "the park", "sparkling water"), ~80 ms per clip."""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from spark_body import models
from spark_body.ear.stt import floats

# Tokens from the model's bpe.model ("HEY SPARK" → ▁HE Y ▁SP AR K), then @ the phrase it reports.
KEYWORDS = (
    "▁HE Y ▁SP AR K @HEY_SPARK",
    "▁HI ▁SP AR K @HI_SPARK",
    "▁O K ▁SP AR K @OK_SPARK",
    "▁OKAY ▁SP AR K @OKAY_SPARK",
)
# Hardware knob: real mics differ from the test clips. Lower → more sensitive, more false alarms.
THRESHOLD = 0.25
BOOST = 1.0
# The spotter fires ~0.4 s after the phrase ends (its encoder looks ahead), so the command starts
# that far back from where it fired. 0.35 to 0.45 s cut cleanly on every test clip; 0.5 s let a
# piece of "Spark" through ("Mark turned the volume…"). Another knob to tune on real voices.
STEP_MS = 50
LOOKBACK_S = 0.4
MIN_COMMAND_S = 0.3  # less audio than this after the phrase: it was just "Hey Spark"

# What STT makes of the wake phrase at the start of a transcript ("Hi Spark," → "I spark,", and
# Whisper's one-word "Hayspark").
_LEADING = re.compile(r"^\W*(?:(?:hey|hi|hay|high|okay|ok|a|i)\W*)?s?parks?\b\W*", re.IGNORECASE)


def strip_wake(text: str) -> str:
    return _LEADING.sub("", text, count=1).strip()


# The second chance (the spotter missed, e.g. a bare "Spark, …"): an on-device transcript that
# starts with the phrase. Stricter than _LEADING: "a spark of genius" must not wake Spark.
_SAID = re.compile(r"^\W*(?:(?:hey|hi|hay|okay|ok)\W*)?sparks?\b", re.IGNORECASE)


def said_wake(text: str) -> bool:
    return bool(_SAID.match(text))


def _fp32(folder: Path, part: str) -> str:
    """The fp32 file: the int8 ones run ~4x slower on CPUs without VNNI."""
    return str(next(p for p in sorted(folder.glob(f"{part}-*.onnx")) if ".int8." not in p.name))


class Wake:
    def __init__(self, root: Path, name: str = "kws-gigaspeech") -> None:
        self.name = name
        self.folder = root / name
        self._kws: Any = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return models.runtime() and models.installed(self.folder.parent, self.name) is not None

    def _load(self) -> Any:
        import sherpa_onnx as so

        d = self.folder
        words = d / "spark_keywords.txt"
        words.write_text("\n".join(KEYWORDS) + "\n", encoding="utf-8")
        return so.KeywordSpotter(
            tokens=str(d / "tokens.txt"),
            encoder=_fp32(d, "encoder"),
            decoder=_fp32(d, "decoder"),
            joiner=_fp32(d, "joiner"),
            keywords_file=str(words),
            num_threads=2,
            keywords_score=BOOST,
            keywords_threshold=THRESHOLD,
        )

    def _find(self, pcm16: bytes, sample_rate: int) -> int | None:
        import numpy as np

        audio = floats(pcm16)
        audio = np.concatenate([audio, np.zeros(sample_rate // 2, dtype=np.float32)])
        step = sample_rate * STEP_MS // 1000
        with self._lock:  # on the worker thread: see mouth.engines._NATIVE
            if self._kws is None:
                self._kws = self._load()
            stream = self._kws.create_stream()
            for start in range(0, len(audio), step):  # in steps, to know where it fired
                stream.accept_waveform(sample_rate, audio[start : start + step])
                while self._kws.is_ready(stream):
                    self._kws.decode_stream(stream)
                    if self._kws.get_result(stream):
                        fired = start + step
                        return max(0, fired - int(LOOKBACK_S * sample_rate))
        return None

    async def warm(self) -> None:
        await self.find(b"\x00\x00" * 8000, 16000)  # load now, not on the first utterance

    async def find(self, pcm16: bytes, sample_rate: int) -> int | None:
        """Where the command starts (a sample index) if the wake phrase is in this utterance,
        else None. STT then hears only the command: "Hey Spark, turn" heard whole came out as
        "He sparked her in" on Moonshine-tiny; cut, it came out right on every test clip."""
        return await asyncio.to_thread(self._find, pcm16, sample_rate)
