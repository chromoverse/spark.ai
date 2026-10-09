"""Tier-1 brain router (REDESIGN §27): intents the brain answers without an LLM, only when sure.
R1 covers stop/cancel and language switching; job status and approvals join with jobs in R2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_STOP = re.compile(
    r"^(?:ok(?:ay)?\s+)?(?:stop|cancel|never ?mind|forget it|shut up)(?: it| that)?$"
)
_LANG = re.compile(
    r"^(?:please\s+)?(?:switch|change|set)\s+(?:the\s+)?(?:language\s+)?(?:to|into)\s+(\w+)"
    r"|^(?:talk|speak|reply|respond)\s+(?:to me\s+)?in\s+(\w+)$"
)
_LANGUAGES = {
    "english": "en",
    "hindi": "hi",
    "nepali": "ne",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "chinese": "zh",
    "arabic": "ar",
    "bengali": "bn",
    "urdu": "ur",
}
SUPPORTED = {"en"}
LANGUAGE_NAMES = {code: name.capitalize() for name, code in _LANGUAGES.items()}


@dataclass(frozen=True)
class Intent:
    kind: Literal["stop", "language"]
    value: str | None = None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def classify(text: str) -> Intent | None:
    t = normalize(text)
    if _STOP.match(t):
        return Intent("stop")
    if m := _LANG.match(t):
        word = m.group(1) or m.group(2)
        if word in _LANGUAGES:
            return Intent("language", _LANGUAGES[word])
    return None


def language_reply(code: str, current: str) -> str:
    """LG1: persona-voiced, settings unchanged until the language ships (§25)."""
    name = LANGUAGE_NAMES.get(code, "That language")
    if code == current:
        return f"We're already on {name}."
    return f"{name}'s not ready yet, it's on the way. Sticking with English for now."
