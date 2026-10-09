"""The eval runner's grading and the latency report (evals/ is dev tooling, but its verdicts
decide chain order and release gates, so they're tested)."""

from __future__ import annotations

import json

from app.llm.types import ToolUse
from evals.latency import collect, pct
from evals.run import grade


def test_reflex_grading() -> None:
    use = ToolUse("c1", "media_play", {"app": "Spotify", "query": "calm"})
    assert grade({"expect": "tool", "tool": "media_play", "args": {"app": "spotify"}}, "", [use])
    assert not grade(
        {"expect": "tool", "tool": "media_play", "args": {"app": "youtube"}}, "", [use]
    )
    assert grade({"expect": "answer"}, "Kathmandu.", [])
    assert not grade({"expect": "answer"}, "Opening it.", [use])  # answered with a tool call
    assert grade(
        {"expect": "delegate"},
        "On it.",
        [ToolUse("c2", "delegate", {"task": "x", "ack": "On it."})],
    )


def test_latency_report_reads_device_and_brain_spans() -> None:
    lines = [
        json.dumps({"msg": "signal trace", "device_spans": {"first_audio": ms, "endpoint": 250}})
        for ms in (700, 800, 900, 1400)
    ] + [
        json.dumps({"msg": "signal done", "tier": 2, "spans": {"ttft": 300, "tool:app_open": 9}}),
        "not json",
    ]
    spans = collect(lines)
    assert spans["device.first_audio"] == [700, 800, 900, 1400]
    assert spans["brain.ttft"] == [300] and "brain.tool:app_open" not in spans
    assert pct(spans["device.first_audio"], 0.5) == 900


def test_persona_rules() -> None:
    from evals.run import persona_misses

    assert (
        persona_misses("[cheerful] Congrats! That's huge. Want to celebrate with a playlist?") == []
    )
    assert "banned phrase" in persona_misses("Certainly! Here you go.")
    assert "markdown/list/link/emoji" in persona_misses("Sure:\n- one\n- two")
    assert "5 sentences" in persona_misses("One. Two. Three. Four. Five.")
    assert "silent" in persona_misses("")
