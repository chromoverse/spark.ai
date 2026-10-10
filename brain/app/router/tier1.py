"""Tier-1 brain router (REDESIGN §27): intents the brain answers without an LLM, only when sure.
Stop/cancel, language switching, job status, and yes / no / always for a pending approval. The
caller drops `status` and `confirm` when no job runs or nothing is pending (then they're just
conversation for the reflex)."""

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
_STATUS = re.compile(
    r"^(?:hey |so )?(?:how'?s it going|how is it going|how'?s (?:that|it|the job) (?:going|coming)"
    r"|(?:any )?(?:status|progress)(?: update)?|are you (?:done|finished)(?: yet)?"
    r"|is it (?:done|finished|ready)(?: yet)?|how far along(?: are you)?"
    r"|what are you (?:doing|working on)|how much longer|how long (?:will it take|left))$"
)
# Bag-of-words confirmations ("okay go ahead", "yes do it please"): every word must be one of
# these, and at least one must carry the decision.
_FILLER = frozenset(
    "it that please go ahead for do sounds good right then now just thing thanks thank you".split()
)
_YES = frozenset(
    "yes yeah yep yup sure ok okay approve approved allow confirm confirmed fine alright".split()
)
_NO = frozenset("no nope nah don't dont not deny cancel never mind skip".split())
_ALWAYS = frozenset({"always"})
SUPPORTED = {"en"}
LANGUAGE_NAMES = {code: name.capitalize() for name, code in _LANGUAGES.items()}


@dataclass(frozen=True)
class Intent:
    kind: Literal["stop", "language", "status", "confirm", "answer"]
    value: str | None = None
    ref: str | None = None  # the approval or question it answers


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def classify(text: str) -> Intent | None:
    t = normalize(text)
    if _STOP.match(t):
        return Intent("stop")
    if _STATUS.match(t):
        return Intent("status")
    if decision := _confirm(t):
        return Intent("confirm", decision)
    if m := _LANG.match(t):
        word = m.group(1) or m.group(2)
        if word in _LANGUAGES:
            return Intent("language", _LANGUAGES[word])
    return None


def _confirm(t: str) -> str | None:
    words = set(t.split())
    if not words or len(t.split()) > 6:
        return None
    if words & _ALWAYS and words <= _ALWAYS | _YES | _FILLER:
        return "always"
    if words & _NO and words <= _NO | _FILLER:
        return "deny"
    if words & (_YES | {"go", "do"}) and words <= _YES | _FILLER:
        return "allow"
    return None


def language_reply(code: str, current: str) -> str:
    """LG1: persona-voiced, settings unchanged until the language ships (§25)."""
    name = LANGUAGE_NAMES.get(code, "That language")
    if code == current:
        return f"We're already on {name}."
    return f"{name}'s not ready yet, it's on the way. Sticking with English for now."
