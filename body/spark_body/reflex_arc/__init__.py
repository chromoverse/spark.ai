"""Tier-0 reflex arc (REDESIGN §27): decide on the device, with no LLM, only when sure."""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from spark_body.reflex_arc.grammar import Match, match

__all__ = ["Match", "Phrases", "decide", "normalize"]

_FILLER = re.compile(
    r"^(?:(?:hey |ok |okay |hi )?spark[, ]+)?"
    r"(?:(?:can|could|would|will) you (?:please )?|please |just |i want you to |go ahead and )*"
)
_TRAIL = re.compile(r"(?: (?:please|thanks|thank you|for me|spark))+$")


def normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")  # curly apostrophes
    t = re.sub(r"[^\w\s'%-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _FILLER.sub("", t)
    t = _TRAIL.sub("", t)
    return t.strip()


def decide(text: str, apps: dict[str, str] | None = None) -> Match | None:
    """A tier-0 match or None (escalate). Never guesses: the grammar needs a full match."""
    return match(normalize(text), apps or {})


class Phrases:
    """Tier-0 replies (PERSONA §4). Actions answer with the chime by default; questions (time,
    date) are spoken. Never the same line twice in a row (PS2)."""

    OPENING = ("Opening {app}.", "{app}, coming up.", "Here's {app}.", "On it.")

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()  # noqa: S311 (variety, not security)
        self.last: dict[str, str] = {}

    def _pick(self, key: str, options: tuple[str, ...]) -> str:
        choices = [o for o in options if o != self.last.get(key)] or list(options)
        line = self.rng.choice(choices)
        self.last[key] = line
        return line

    def reply(self, m: Match, output: dict[str, Any], now: datetime, chatty: bool = False) -> str:
        """'' means chime only."""
        if m.intent == "time_now":
            return f"It's {now.strftime('%I:%M %p').lstrip('0')}."
        if m.intent == "date_today":
            day = now.day
            suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            return f"It's {now.strftime('%A, %B')} {day}{suffix}."
        if m.intent == "app_open":
            name = str(output.get("opened") or m.slots.get("app", "it"))
            return self._pick("app_open", self.OPENING).format(app=name)
        if chatty and m.intent in {"volume_set", "brightness_set"}:
            what = "Volume" if m.intent == "volume_set" else "Brightness"
            return f"{what} at {m.slots['level']}."
        return ""
