"""Clips for the latency bench's scripted ear (TESTING.md §6): each line of `latency.jsonl`
becomes "Hey Spark, <text>" spoken by the on-device Piper voice (a few speakers), as 16 kHz mono
PCM16 WAVs with the silence the live ear's VAD keeps around speech, plus `manifest.json`.

    uv run python -m evals.clips [out_dir]   # default %LOCALAPPDATA%/SparkAI/latency-clips

Then start the desktop app with SPARK_VOICE_SCRIPT=<out_dir>/manifest.json.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np

from spark_body import models
from spark_body.app import data_dir
from spark_body.mouth.engines import LocalTts, wav

RATE = 16_000
SPEAKERS = (0, 20, 60, 120, 240)  # LibriTTS-R voices, rotated per clip
PAD_BEFORE_S, PAD_AFTER_S = 0.12, 0.25  # vad-web's pre-speech pad and the 250 ms candidate


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else data_dir() / "latency-clips"
    out.mkdir(parents=True, exist_ok=True)
    root = data_dir() / "models"
    piper = next(m for m in models.CATALOG if m.name == "piper")
    voice = LocalTts(piper, root)
    if not voice.available():
        print("Piper isn't downloaded yet: start the body once (it fetches its models).")
        return 1
    rows = [json.loads(line) for line in (Path(__file__).parent / "latency.jsonl").open()]
    manifest = []
    for i, row in enumerate(rows):
        voice.model = dataclasses.replace(piper, sid=SPEAKERS[i % len(SPEAKERS)])
        clip = voice._generate(f"Hey Spark, {row['text']}")
        rate = int.from_bytes(clip[24:28], "little")
        audio = np.frombuffer(clip[44:], dtype="<i2").astype(np.float32)
        n = round(len(audio) * RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
        pad = lambda s: np.zeros(round(s * RATE), dtype=np.float32)  # noqa: E731
        pcm = np.concatenate([pad(PAD_BEFORE_S), audio, pad(PAD_AFTER_S)]).astype("<i2").tobytes()
        name = f"{i + 1:02d}.wav"
        (out / name).write_bytes(wav(pcm, RATE))
        manifest.append({"wav": name, "wake": True} | {k: v for k, v in row.items() if k != "text"})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(manifest)} clips in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
