"""Local text embeddings (REDESIGN §8): multilingual-e5-small, int8 ONNX, 384 numbers per text,
~6 ms for a short line on a laptop CPU (int8 ran faster than fp32 here, same ranking), no network
once downloaded. The model downloads on the brain's first start, sha256 pinned; until it's ready
memory search runs on full-text alone."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DIM = 384
MODEL = "multilingual-e5-small"
_HF = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/761b726dd34fb83930e26aab4e9ac3899aa1fa78"
FILES = {  # name → (url, sha256)
    "model.onnx": (
        f"{_HF}/onnx/model_quantized.onnx",
        "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
    ),
    "tokenizer.json": (
        f"{_HF}/tokenizer.json",
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
}
MAX_TOKENS = 128  # memories and spoken lines are short


class Embedder:
    """`embed` returns unit vectors, or None while the model isn't loaded. e5 wants "query: " on
    searches and "passage: " on what's stored."""

    # Cosine floors, measured on e5 (2026-10-11): a related query/memory pair scores 0.79-0.84,
    # an unrelated one 0.71-0.78; a paraphrase 0.96-0.99, but so is a flipped preference ("dark
    # mode" / "light mode" 0.96), and two different sisters score 0.92.
    related = 0.77
    same = 0.95

    def __init__(self, models_dir: str) -> None:
        self.dir = Path(models_dir) / MODEL
        self._session: Any = None
        self._tok: Any = None

    @property
    def ready(self) -> bool:
        return self._session is not None

    async def start(self, http: httpx.AsyncClient) -> None:
        """Download (first start) and load. Failures leave it off; the next start retries."""
        try:
            if not (self.dir / ".ok").exists():
                await self._download(http)
            await asyncio.to_thread(self._load)
            await self.embed(["warm up"], query=True)  # the first run is ~3x slower
            logger.info("embedder ready", extra={"model": MODEL})
        except Exception:
            logger.warning("embedder unavailable, memory search uses full-text", exc_info=True)

    async def _download(self, http: httpx.AsyncClient) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for name, (url, sha) in FILES.items():
            part = self.dir / f"{name}.part"
            digest = hashlib.sha256()
            async with http.stream("GET", url, follow_redirects=True, timeout=120) as r:
                r.raise_for_status()
                with part.open("wb") as f:
                    async for chunk in r.aiter_bytes(1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
            if digest.hexdigest() != sha:
                part.unlink()
                raise ValueError(f"{name}: checksum mismatch")
            part.replace(self.dir / name)
        (self.dir / ".ok").touch()

    def _load(self) -> None:
        import onnxruntime as ort  # heavy imports only where the model runs
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
        tok.enable_truncation(MAX_TOKENS)
        tok.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2  # the brain shares the CPU with everything else
        self._session = ort.InferenceSession(
            str(self.dir / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self._tok = tok

    async def embed(self, texts: Sequence[str], *, query: bool) -> list[list[float]] | None:
        if not self.ready or not texts:
            return None
        prefix = "query: " if query else "passage: "
        return await asyncio.to_thread(self._run, [prefix + t for t in texts])

    def _run(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        enc = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if any(i.name == "token_type_ids" for i in self._session.get_inputs()):
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / m.sum(axis=1)  # mean over real tokens (e5)
        unit = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
        out: list[list[float]] = unit.tolist()
        return out
