"""Tier-0 reflex arc (TESTING.md §4.3 RA1, RA2; §4.8 PS2). # proves §27"""

from __future__ import annotations

import itertools
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from spark_body.reflex_arc import Match, Phrases, decide, normalize

EVAL = Path(__file__).resolve().parents[1] / "evals" / "reflex_arc.jsonl"
APPS = {
    "spotify": "Spotify",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "notepad": "Notepad",
    "calculator": "Calculator",
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "vlc": "VLC media player",
    "discord": "Discord",
}


def rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines() if line]


def test_ra1_eval_false_accept_and_slot_accuracy() -> None:
    data = rows()
    assert len(data) >= 300
    negatives = [r for r in data if r["intent"] is None]
    positives = [r for r in data if r["intent"] is not None]
    false_accepts = [r["text"] for r in negatives if decide(r["text"], APPS) is not None]
    assert len(false_accepts) / len(negatives) < 0.005, false_accepts
    right = 0
    for r in positives:
        m = decide(r["text"], APPS)
        right += m is not None and (m.intent, m.slots) == (r["intent"], r["slots"])
    assert right / len(positives) >= 0.98


def test_ra2_destructive_send_purchase_never_tier0() -> None:
    never = [r["text"] for r in rows() if r["kind"] == "never"]
    assert len(never) >= 25
    assert [t for t in never if decide(t, APPS) is not None] == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hey Spark, could you please turn it up?", Match("volume_change", {"direction": "up"})),
        ("volume to seventy-five percent", Match("volume_set", {"level": 75})),
        ("set the volume to 300", None),  # slot out of range: not sure → escalate
        ("open spotify", Match("app_open", {"app": "Spotify"})),
        ("open photoshop", None),  # not installed here
        ("open youtube on my phone", None),  # a device target is tier 1+
        ("play something calm", None),
    ],
)
def test_decide_is_sure_or_escalates(text: str, expected: Match | None) -> None:
    assert decide(text, APPS) == expected


def test_normalize_strips_wake_words_and_politeness() -> None:
    assert normalize("Hey Spark, can you please pause the music, thanks!") == "pause the music"
    assert normalize("What\u2019s the time?") == "what's the time"


def test_ps2_acknowledgements_never_repeat_back_to_back() -> None:
    phrases = Phrases(random.Random(1))
    now = datetime(2026, 10, 10, 14, 5)
    said = [
        phrases.reply(Match("app_open", {"app": "Spotify"}), {"opened": "Spotify"}, now)
        for _ in range(10)
    ]
    assert all(a != b for a, b in itertools.pairwise(said))
    assert len(set(said)) > 1


def test_tier0_replies_chime_for_actions_and_speak_answers() -> None:
    phrases = Phrases(random.Random(1))
    now = datetime(2026, 10, 10, 14, 5)
    assert phrases.reply(Match("volume_set", {"level": 30}), {}, now) == ""  # chime only
    assert (
        phrases.reply(Match("volume_set", {"level": 30}), {}, now, chatty=True) == "Volume at 30."
    )
    assert phrases.reply(Match("time_now"), {}, now) == "It's 2:05 PM."
    assert phrases.reply(Match("date_today"), {}, now) == "It's Saturday, October 10th."
