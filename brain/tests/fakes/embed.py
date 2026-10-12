"""Deterministic stand-in for the ONNX embedder: words hashed into 384 dims, so lines that share
words point the same way. Instant, no model, no network."""

from __future__ import annotations

import hashlib
import math
import re
import tempfile
from collections.abc import Sequence

import httpx

from app.memory.embed import DIM, Embedder
from app.memory.store import _STOP


class FakeEmbedder(Embedder):
    related = 0.3

    def __init__(self) -> None:
        super().__init__(tempfile.gettempdir())
        self.on = True  # off = the model isn't downloaded yet: full-text only

    @property
    def ready(self) -> bool:
        return self.on

    async def start(self, http: httpx.AsyncClient) -> None:
        return None

    async def embed(self, texts: Sequence[str], *, query: bool) -> list[list[float]] | None:
        if not self.on or not texts:
            return None
        return [vector(t) for t in texts]


def vector(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in re.findall(r"\w+", text.lower()):
        if w not in _STOP:
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0  # noqa: S324
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v] if any(v) else [1.0 / math.sqrt(DIM)] * DIM
