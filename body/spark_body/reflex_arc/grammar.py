"""Tier-0 grammar (REDESIGN §27): a closed set of intents, matched only when the whole utterance
fits a pattern and every slot resolves. Anything else returns None and goes to the brain.
Nothing destructive, sending, or purchasing is in here, by construction (RA2)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORDS = {
    "half": 50,
    "max": 100,
    "maximum": 100,
    "full": 100,
    "a hundred": 100,
    "hundred": 100,
    "one hundred": 100,
}

NUM = r"(?P<n>\d{1,3}|(?:a |one )?hundred|half|max(?:imum)?|full|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"  # noqa: E501
PCT = r"(?: ?%| percent| per cent)?"


def number(text: str) -> int | None:
    t = text.strip().replace("-", " ")
    if t.isdigit():
        return int(t)
    if t in _WORDS:
        return _WORDS[t]
    if t in _UNITS:
        return _UNITS[t]
    parts = t.split()
    if parts and parts[0] in _TENS:
        if len(parts) == 1:
            return _TENS[parts[0]]
        if len(parts) == 2 and parts[1] in _UNITS and 0 < _UNITS[parts[1]] < 10:
            return _TENS[parts[0]] + _UNITS[parts[1]]
    return None


@dataclass(frozen=True)
class Match:
    intent: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


Slots = Callable[[re.Match[str]], dict[str, Any] | None]


@dataclass(frozen=True)
class Rule:
    intent: str
    patterns: tuple[re.Pattern[str], ...]
    slots: Slots = lambda m: {}


def _rule(intent: str, patterns: Iterable[str], slots: Slots | None = None) -> Rule:
    compiled = tuple(re.compile(f"^(?:{p})$") for p in patterns)
    return Rule(intent, compiled, slots or (lambda m: {}))


def _level(m: re.Match[str]) -> dict[str, Any] | None:
    n = number(m.group("n"))
    return {"level": n} if n is not None and 0 <= n <= 100 else None


def _step(direction: str) -> Slots:
    def slots(m: re.Match[str]) -> dict[str, Any] | None:
        out: dict[str, Any] = {"direction": direction}
        if "n" in m.groupdict() and m.group("n"):
            n = number(m.group("n"))
            if n is None or not 1 <= n <= 50:
                return None
            out["step"] = n
        return out

    return slots


_IT = r"(?:it|the volume|volume|the sound|sound|the music|music|that)"
_MEDIA = r"(?:the )?(?:music|song|track|video|playback|audio|podcast|it|this)"

RULES: tuple[Rule, ...] = (
    _rule(
        "volume_set",
        [
            rf"(?:set |turn |put |change )?(?:the )?(?:volume|sound) (?:to |at )?{NUM}{PCT}",
            rf"(?:set |turn |put )?{_IT} (?:to |at ){NUM}{PCT}(?: volume)?",
            rf"volume {NUM}{PCT}",
        ],
        _level,
    ),
    _rule(
        "volume_change",
        [
            rf"(?:turn |crank |bring |pump )?{_IT} up(?: a (?:bit|little|notch))?",
            rf"turn up {_IT}(?: a (?:bit|little|notch))?",
            r"(?:a (?:bit|little) )?louder(?: please)?",
            r"(?:increase|raise) (?:the )?(?:volume|sound)",
            rf"(?:volume|sound) up(?: by {NUM}{PCT})?",
            rf"(?:turn |raise )?(?:the )?volume up by {NUM}{PCT}",
        ],
        _step("up"),
    ),
    _rule(
        "volume_change",
        [
            rf"(?:turn |bring )?{_IT} down(?: a (?:bit|little|notch))?",
            rf"turn down {_IT}(?: a (?:bit|little|notch))?",
            r"(?:a (?:bit|little) )?(?:quieter|softer)(?: please)?",
            r"(?:decrease|lower|reduce) (?:the )?(?:volume|sound)",
            rf"(?:volume|sound) down(?: by {NUM}{PCT})?",
            rf"(?:turn |lower )?(?:the )?volume down by {NUM}{PCT}",
        ],
        _step("down"),
    ),
    _rule(
        "volume_mute",
        [r"mute(?: (?:the )?(?:sound|volume|audio|it|everything))?"],
        lambda m: {"mute": True},
    ),
    _rule(
        "volume_mute",
        [r"un ?mute(?: (?:the )?(?:sound|volume|audio|it))?"],
        lambda m: {"mute": False},
    ),
    _rule(
        "media_control",
        [
            r"play",
            r"resume(?: " + _MEDIA + ")?",
            r"continue (?:the )?(?:music|song|video)",
            r"(?:un ?pause|start) (?:the )?(?:music|song|video)",
            r"keep playing",
        ],
        lambda m: {"action": "play"},
    ),
    _rule(
        "media_control",
        [
            r"pause(?: " + _MEDIA + ")?",
            r"stop (?:the )?(?:music|song|video|playback)",
            r"hold (?:the )?(?:music|song)",
        ],
        lambda m: {"action": "pause"},
    ),
    _rule(
        "media_control",
        [
            r"next(?: (?:song|track|one|video|episode))?(?: please)?",
            r"skip(?: (?:this|the|that) (?:song|track|one|video))?(?: please)?",
            r"skip it",
            r"play the next (?:song|track|one|video)",
            r"go to the next (?:song|track)",
        ],
        lambda m: {"action": "next"},
    ),
    _rule(
        "media_control",
        [
            r"previous(?: (?:song|track|one|video))?",
            r"(?:go )?back a (?:song|track)",
            r"(?:play the |go to the )?(?:previous|last) (?:song|track|one|video)",
            r"play (?:that|the) (?:song|track) again",
        ],
        lambda m: {"action": "previous"},
    ),
    _rule(
        "brightness_set",
        [
            rf"(?:set |turn |put |change )?(?:the )?(?:screen |display )?"
            rf"brightness (?:to |at )?{NUM}{PCT}",
            rf"brightness {NUM}{PCT}",
        ],
        _level,
    ),
    _rule(
        "time_now",
        [
            r"what(?: is|'s|s)? the time(?: now| right now)?",
            r"what time is it(?: now| right now)?",
            r"(?:tell me |give me )?the time(?: please)?",
            r"time(?: please)?",
            r"what time(?: is it)? (?:now|right now)",
            r"current time",
            r"do you know (?:the|what) time(?: it is)?",
        ],
    ),
    _rule(
        "date_today",
        [
            r"what(?: is|'s|s)? (?:the |today's |todays )?date(?: today)?",
            r"what day is (?:it|today)(?: today)?",
            r"what(?: is|'s|s)? today",
            r"today's date",
            r"(?:tell me )?(?:the |today's )?date(?: please)?",
            r"what day of the week is (?:it|today)",
        ],
    ),
    _rule(
        "stop",
        [
            # "okay, stop, stop" / "hey stop" / "no no stop it": said in a hurry while Spark talks
            r"(?:(?:ok(?:ay)?|hey|no|please) )*stop(?: stop)*(?: it| that| talking| now)?",
            r"cancel(?: it| that)?",
            r"never ?mind",
            r"forget (?:it|that)",
            r"(?:be )?quiet",
            r"shut up",
            r"enough",
            r"that(?:'s| is) enough",
            r"hush",
        ],
    ),
    _rule(
        "repeat",
        [
            r"repeat(?: that| it)?(?: please)?",
            r"say (?:that|it) again(?: please)?",
            r"what did you (?:just )?say",
            r"come again",
            r"pardon",
        ],
    ),
)

_OPEN = re.compile(
    r"^(?:open|launch|start|run|fire up|bring up|pull up)(?: up)? (?:the )?"
    r"(?P<app>.+?)(?: app| application| for me)?$"
)
_NOT_AN_APP = re.compile(
    r"\b(?:on (?:my|the)|and|then|file|folder|website|site|page|document|tab|window|door|link|"
    r"email|mail from|message|settings for|http|www|\.com)\b"
)


def match(text: str, apps: dict[str, str]) -> Match | None:
    """`text` is already normalized. `apps` maps lowercase spoken names → the app's id on this
    device; app_open is only accepted for an exact hit (the app must exist, §27)."""
    for rule in RULES:
        for pattern in rule.patterns:
            m = pattern.match(text)
            if m is None:
                continue
            slots = rule.slots(m)
            if slots is None:
                return None  # matched the shape but a slot didn't resolve: not sure
            return Match(rule.intent, slots)
    m = _OPEN.match(text)
    if m and not _NOT_AN_APP.search(m.group("app")):
        app = apps.get(m.group("app"))
        if app is not None:
            return Match("app_open", {"app": app})
    return None
