"""The eval runner's grading and the latency report (evals/ is dev tooling, but its verdicts
decide chain order and release gates, so they're tested)."""

from __future__ import annotations

import json
from pathlib import Path

from app.llm.types import ToolUse
from app.tools import registry
from evals.latency import collect, pct
from evals.run import grade

EVALS = Path(__file__).resolve().parents[1] / "evals"


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


def test_latency_report_splits_first_audio_by_tier() -> None:
    trace = {"msg": "signal trace"}
    lines = [
        json.dumps(trace | {"signal_id": "a", "device_spans": {"first_audio": 850}}),
        json.dumps(trace | {"signal_id": "b", "device_spans": {"first_audio": 1300}}),
        json.dumps({"msg": "signal done", "signal_id": "a", "tier": 0, "spans": {"end": 9}}),
        json.dumps({"msg": "signal done", "signal_id": "b", "tier": 2, "spans": {"ttft": 470}}),
    ]
    spans = collect(lines)
    assert spans["device.first_audio.tier0"] == [850]
    assert spans["device.first_audio.tier2"] == [1300]


def test_persona_rules() -> None:
    from evals.run import persona_misses

    assert (
        persona_misses("[cheerful] Congrats! That's huge. Want to celebrate with a playlist?") == []
    )
    assert "banned phrase" in persona_misses("Certainly! Here you go.")
    assert "markdown/list/link/emoji" in persona_misses("Sure:\n- one\n- two")
    assert "5 sentences" in persona_misses("One. Two. Three. Four. Five.")
    assert "silent" in persona_misses("")


def test_agent_eval_rows_name_real_tools_and_grade_offline() -> None:
    """The agent eval file can't drift from the catalog; grading works without a network."""
    from evals.agent import Run, grade

    rows = [json.loads(line) for line in (EVALS / "agent.jsonl").read_text().splitlines() if line]
    assert len(rows) >= 30 and len({r["id"] for r in rows}) == len(rows)
    for row in rows:
        named = [*row.get("calls", []), *row.get("calls_any", []), *row.get("forbid", [])]
        named += [*row.get("tools", {}), *row.get("deny", []), *row.get("forbid_args", {})]
        unknown = [n for n in named if n not in registry.BY_NAME]
        assert not unknown, (row["id"], unknown)
    notes = next(r for r in rows if r["id"] == "notes")
    good = Run(names=["file_write", "file_open"], final="Done. Your to-dos are in notes.txt.")
    good.evidence = [notes["request"], '{"path": "Desktop/notes.txt"}']
    assert grade(notes, good) is None
    assert grade(notes, Run(names=["file_write"], final="Done.")) == "never called ['file_open']"
    made_up = Run(names=["file_write", "file_open"], final="Saved notes.txt and todo.docx.")
    made_up.evidence = good.evidence
    assert grade(notes, made_up).startswith("ungrounded")  # type: ignore[union-attr]


def test_memory_rows_grade_what_was_remembered() -> None:
    from app.memory.extract import Item
    from evals.run import grade_memory, turn_prompt

    asha = Item(kind="person", text="The user's sister is Asha.", importance=0.9)
    row = {"expect": [{"kind": "person", "words": ["sister", "asha"]}]}
    assert grade_memory(row, [asha]) and not grade_memory(row, [])
    assert not grade_memory({"expect": []}, [asha])  # nothing to learn: nothing learned
    short = Item(kind="preference", text="The user wants brief replies.", importance=0.6)
    assert grade_memory({"expect": [{"words": ["short|brief"]}]}, [short])
    moved = Item(kind="correction", text="The user lives in Pokhara.", importance=0.6, replaces=1)
    fix = {"expect": [{"words": ["Pokhara"]}], "replaces": 1}
    assert grade_memory(fix, [moved]) and not grade_memory(
        fix, [moved.model_copy(update={"replaces": None})]
    )

    # reflex rows: what's remembered reaches the prompt like a real turn's, and is graded
    system, said = turn_prompt({"text": "call my sister", "profile": "The user's sister is Asha.",
                                "remembered": "The user's wifi is Lotus."})  # fmt: skip
    assert system.endswith("What you know about the user: The user's sister is Asha.")
    assert said.startswith("call my sister\n\n(context: it's Saturday 10 October 2026, 2:05 PM")
    assert said.endswith("remembered: The user's wifi is Lotus.)")
    mentions = {"expect": "mentions", "words": ["Asha"], "not_words": ["Usha"]}
    assert grade(mentions, "I can't call yet. Text Asha?", [])
    assert not grade(mentions, "Calling Usha.", [])
    assert not grade(mentions, "On it.", [ToolUse("c3", "delegate", {"task": "call Asha"})])
