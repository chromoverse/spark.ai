"""The real memory embedder (multilingual-e5-small). Runs only where the brain has downloaded
it (`brain/data/models`, first start); CI and fresh checkouts skip it.
# proves §8 (local embeddings)"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.memory.embed import MODEL, Embedder

MODELS = Path(__file__).resolve().parents[1] / "data" / "models"
pytestmark = pytest.mark.skipif(
    not (MODELS / MODEL / ".ok").exists(), reason="embedder not downloaded (brain first start)"
)

MEMORIES = [
    "The user's sister is Asha.",
    "The user prefers dark mode in every app.",
    "The user's wife Priya was born on 4 March.",
    "The user likes lo-fi music while working.",
    "The user is vegetarian and avoids sugar.",
    "The user works at a bank in Kathmandu.",
]


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_real_embedder_finds_the_right_memory_fast() -> None:
    e = Embedder(str(MODELS))
    e._load()
    mems = await e.embed(MEMORIES, query=False)
    assert mems is not None and len(mems[0]) == 384
    for query, want in [
        ("call my sister", 0),
        ("what's my wife's birthday", 2),
        ("play something I like", 3),
        ("what should I eat tonight", 4),
    ]:
        [q] = await e.embed([query], query=True) or [[]]
        sims = [cos(q, m) for m in mems]
        assert max(range(len(sims)), key=sims.__getitem__) == want, query
        assert sims[want] >= e.related, query
    [moon] = await e.embed(["how far is the moon"], query=True) or [[]]
    assert max(cos(moon, m) for m in mems) < e.related  # nothing related: nothing in the prompt

    took = []
    for i in range(20):
        t0 = time.perf_counter()
        await e.embed([f"remind me about my diet {i}"], query=True)
        took.append((time.perf_counter() - t0) * 1000)
    assert sorted(took)[10] < 15, f"p50 {sorted(took)[10]:.1f} ms"
