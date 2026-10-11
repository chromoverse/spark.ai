"""One tool catalog (REDESIGN §7, §21). Free models get a lean prompt: the agent sees the brain
tools plus the device tools that fit the task (a keyword pre-selector) and can ask tool_search for
more. Catalog order is fixed so a given tool set always renders the same prompt prefix."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from app.memory.tools import MEMORY_TOOLS
from app.tools.brain_specs import BRAIN_TOOLS
from app.tools.device_specs import DEVICE_TOOLS, QUICK_TOOLS
from app.tools.spec import ToolSpec

# Brain tools with a handler (integrations, R4). The loop runs them like device tools: hooks,
# permissions, steps; they just execute in the brain.
INTEGRATIONS: list[ToolSpec] = []
ALL: tuple[ToolSpec, ...] = (*BRAIN_TOOLS, *QUICK_TOOLS, *DEVICE_TOOLS, *MEMORY_TOOLS)
BY_NAME: dict[str, ToolSpec] = {t.name: t for t in ALL}
ORDER = {t.name: i for i, t in enumerate(ALL)}


def register(spec: ToolSpec) -> None:
    INTEGRATIONS.append(spec)
    BY_NAME[spec.name] = spec
    ORDER[spec.name] = len(ORDER)


PICK = 8  # device tools per job for free models (§21: "top 8 tools for the task")
STARTER = ("file_list", "file_read")  # looking around is part of almost every job
FALLBACK = ("file_list", "file_read", "file_search", "file_write", "file_open", "app_open")
_STOP = frozenset(
    "the a an and or to of in on for my me it is are be with this that from at by please can "
    "you your i want need just then some all".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in _STOP}


_NAMES = Counter(w for t in ALL for w in _words(t.name.replace("_", " ")))


def _score(spec: ToolSpec, words: set[str]) -> int:
    """A word naming the tool beats a keyword beats the description: "clipboard" in the task
    must outrank file tools that merely share "desktop"."""
    named = _words(spec.name.replace("_", " "))
    strong = _words(spec.keywords)
    weak = _words(spec.description)

    def weight(w: str) -> int:
        if w in named:
            return 3 if _NAMES[w] <= 2 else 1  # "file" names eight tools: it picks none of them
        return 2 if w in strong else 1 if w in weak else 0

    return sum(weight(w) for w in words)


def usable(capabilities: Iterable[str], hidden: Iterable[str] = ()) -> list[ToolSpec]:
    """Tools some device can run (and brain tools with a handler), minus tools a bare deny rule
    removed (§20.6)."""
    caps, gone = frozenset(capabilities), frozenset(hidden)
    pool = (*QUICK_TOOLS, *DEVICE_TOOLS, *MEMORY_TOOLS, *INTEGRATIONS)
    return [t for t in pool if t.requires <= caps and t.name not in gone]


def search(query: str, pool: list[ToolSpec], limit: int) -> list[ToolSpec]:
    # ponytail: keyword overlap; the embedding pre-selector replaces it when the ONNX model
    # lands with memory (R3)
    words = _words(query)
    ranked = sorted(
        ((s, t) for t in pool if (s := _score(t, words)) > 0),
        key=lambda x: (-x[0], ORDER[x[1].name]),
    )
    return sorted((t for _, t in ranked[:limit]), key=lambda t: ORDER[t.name])


def select(task: str, capabilities: Iterable[str], hidden: Iterable[str] = ()) -> list[ToolSpec]:
    """The agent's starting tools: brain tools, then the device tools that fit the task."""
    pool = usable(capabilities, hidden)
    picked = search(task, pool, PICK) or [t for t in pool if t.name in FALLBACK]
    picked += [t for t in pool if t.name in STARTER and t not in picked]
    gone = frozenset(hidden)
    devices = sorted(picked, key=lambda t: ORDER[t.name])
    return [*(t for t in BRAIN_TOOLS if t.name not in gone), *devices]
