"""Tier-1 brain router (REDESIGN §27): intents the brain answers without an LLM, only when sure.
Stop/cancel, language switching, job status, yes / no / always for something pending, simple
commands aimed at another device ("pause the music on my laptop", §26.4-F), and handoffs ("send
this to my phone", "continue on my phone"). The caller drops an intent it can't be sure of: no
job running, nothing pending, or no single online device matching (then the reflex takes it)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

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
_DEV = r"(?:my|the) (?P<dev>[\w' -]{2,30})"
_ON = rf"(?:on|from) {_DEV}"
_MEDIA = r"(?: the)?(?: music| song| video| track| it| media)?"
# pattern → (tool, slots, what Spark says before " on your <device>.")
_REMOTE: tuple[tuple[re.Pattern[str], str, dict[str, Any], str], ...] = tuple(
    (re.compile(p), tool, slots, say)
    for p, tool, slots, say in (
        (rf"^(?:pause|stop){_MEDIA} {_ON}$", "media_control", {"action": "pause"}, "Paused"),
        (
            rf"^(?:play|resume|unpause){_MEDIA} {_ON}$",
            "media_control",
            {"action": "play"},
            "Playing",
        ),
        (
            rf"^(?:next|skip)(?: the)?(?: song| track| one)? {_ON}$",
            "media_control",
            {"action": "next"},
            "Skipped",
        ),
        (
            rf"^(?:previous|go back)(?: song| track)? {_ON}$",
            "media_control",
            {"action": "previous"},
            "Going back",
        ),
        (rf"^mute(?: it)? {_ON}$", "volume_mute", {"mute": True}, "Muted"),
        (rf"^unmute(?: it)? {_ON}$", "volume_mute", {"mute": False}, "Unmuted"),
        (
            rf"^(?:turn )?(?:the )?volume up {_ON}$",
            "volume_change",
            {"direction": "up"},
            "Turned it up",
        ),
        (
            rf"^(?:turn )?(?:the )?volume down {_ON}$",
            "volume_change",
            {"direction": "down"},
            "Turned it down",
        ),
    )
)
_VOLUME_TO = re.compile(
    rf"^(?:set |turn )?(?:the )?volume (?:to )?(?P<n>\d{{1,3}})(?: percent)? {_ON}$"
)
_HANDOFF = re.compile(rf"^(?:send|share|push) (?:this|that|it)(?: over)? to {_DEV}$")
_CONTINUE = re.compile(
    rf"^(?:continue|pick (?:this|it) up|carry on)(?: this| it| here)? (?:on|from) {_DEV}$"
)
SUPPORTED = {"en"}
LANGUAGE_NAMES = {code: name.capitalize() for name, code in _LANGUAGES.items()}


@dataclass(frozen=True)
class Intent:
    kind: Literal[
        "stop", "language", "status", "confirm", "answer", "remote", "handoff", "continue"
    ]
    value: str | None = None  # language code, decision, or tool
    ref: str | None = None  # the approval or question it answers, or the device word
    slots: dict[str, Any] | None = None  # remote: the tool's input
    say: str | None = None  # remote: the phrase before " on your <device>."


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
    for pattern, tool, slots, say in _REMOTE:
        if m := pattern.match(t):
            return Intent("remote", tool, m.group("dev"), dict(slots), say)
    if (m := _VOLUME_TO.match(t)) and int(m.group("n")) <= 100:
        return Intent(
            "remote",
            "volume_set",
            m.group("dev"),
            {"level": int(m.group("n"))},
            f"Volume's at {m.group('n')}",
        )
    if m := _HANDOFF.match(t):
        return Intent("handoff", None, m.group("dev"))
    if m := _CONTINUE.match(t):
        return Intent("continue", None, m.group("dev"))
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
