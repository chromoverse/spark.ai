"""R2 agent loop + jobs over the real gateway (TESTING.md §4.1 D1, §4.3 RA3, RA4, §4.5 S2/S4/S5/S7,
§4.6 T1 to T4, §4.8 PS3, PHASES R2 acceptance). # proves §5.2, §6.1, §6.4, §7.2, §19, §20.5 + 6"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Approval, Artifact, Incident, Job, JobStep, Message, PermissionRule
from app.tools import registry
from app.tools.spec import Risk, ToolSpec
from tests.conftest import Brain
from tests.fakes.clock import drive, until
from tests.fakes.device import FakeDevice
from tests.fakes.llm import Turn

pytestmark = pytest.mark.scenario

CAPS = ["apps", "volume", "media", "brightness", "files", "shell", "clipboard", "input", "system"]
TERMINAL = ("done", "failed", "cancelled")


@pytest.fixture
async def laptop(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Laptop"))
    await d.connect()
    await d.hello(capabilities=CAPS)
    yield d
    await d.close()


def tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"name": name, "arguments": arguments}


def delegate(task: str, said: str = "On it.") -> Turn:
    return Turn(text=[said], tool_calls=[tool("delegate", task=task, ack="On it.")])


def spoken(deltas: list[dict[str, Any]]) -> list[str]:
    return [d["text"] for d in deltas if d["speak"]]


async def updates(
    dev: FakeDevice, until_status: tuple[str, ...] = TERMINAL, within: float = 5
) -> list[dict[str, Any]]:
    """job.update events up to the first with one of `until_status`."""
    seen = []
    while True:
        ev = await dev.next("job.update", within)
        seen.append(ev)
        if ev["status"] in until_status:
            return seen


async def rows(brain: Brain, model: Any) -> list[Any]:
    async with brain.rt.db() as db:
        return list((await db.scalars(select(model))).all())


def tool_calls(dev: FakeDevice, name: str) -> list[dict[str, Any]]:
    return [d for e, d in dev.inbox if e == "tool.call" and d["tool"] == name]


async def test_notes_txt_completes_with_progress_shown(brain: Brain, laptop: FakeDevice) -> None:
    """PHASES R2: "Create notes.txt on the desktop, write my to-dos, open it"."""
    assert brain.groq is not None
    brain.groq.queue(
        delegate("Create notes.txt on the desktop with my to-dos (buy milk, call mom) and open it")
    )
    brain.groq.queue(
        Turn(
            tool_calls=[
                tool(
                    "todo_write", items=[{"text": "Write notes.txt"}, {"text": "Open it"}], eta_s=20
                )
            ]
        ),
        Turn(
            text=["Writing it now."],
            tool_calls=[
                tool("file_write", path="Desktop/notes.txt", content="- buy milk\n- call mom\n")
            ],
        ),
        Turn(tool_calls=[tool("file_open", path="Desktop/notes.txt")]),
        Turn(text=["Done. Your to-dos are in notes.txt on your desktop, and it's open."]),
        model="agent",
    )
    brain.groq.queue(Turn(text=["ALLOW"]), model="review")
    laptop.tools["file_write"] = {
        "ok": True,
        "output": {"path": "C:/Users/asha/Desktop/notes.txt", "bytes": 22},
    }
    laptop.tools["file_open"] = {"ok": True, "output": {"opened": "notes.txt"}}

    sid, ack = await laptop.say(
        "create notes.txt on the desktop, write my to-dos: buy milk, call mom, and open it"
    )
    assert ack["data"]["tier"] == 2
    assert spoken(await laptop.reply(sid)) == ["On it."]
    seen = await updates(laptop)
    statuses = [u["status"] for u in seen]
    assert statuses[0] == "queued" and "running" in statuses and statuses[-1] == "done"
    assert any(len(u["todo"]) == 2 for u in seen)  # the checklist reached the device
    steps = [(u["step"]["tool"], u["step"]["status"]) for u in seen if "step" in u]
    assert steps == [
        ("file_write", "running"),
        ("file_write", "ok"),
        ("file_open", "running"),
        ("file_open", "ok"),
    ]
    assert any(u.get("note") == "Writing it now." for u in seen)  # progress note, on screen
    assert spoken(await laptop.reply(sid)) == [
        "Done.",
        "Your to-dos are in notes.txt on your desktop, and it's open.",
    ]

    calls = [d for e, d in laptop.inbox if e == "tool.call"]
    assert [c["tool"] for c in calls] == ["file_write", "file_open"]
    assert all(c["job_id"] == seen[0]["job_id"] for c in calls)
    [job] = await rows(brain, Job)
    assert (job.status, job.summary) == (
        "done",
        "Done. Your to-dos are in notes.txt on your desktop, and it's open.",
    )
    assert job.todo == [
        {"text": "Write notes.txt", "status": "pending"},
        {"text": "Open it", "status": "pending"},
    ]
    steps_db = sorted(await rows(brain, JobStep), key=lambda s: s.started_at)
    assert [(s.tool, s.status) for s in steps_db] == [("file_write", "ok"), ("file_open", "ok")]
    msgs = await rows(brain, Message)
    assert any(m.tier == 3 and m.role == "assistant" for m in msgs)  # the wrap-up is in the thread
    first = brain.groq.for_model("agent")[0]
    offered = {t["function"]["name"] for t in first["tools"]}
    assert {"todo_write", "file_write", "file_open"} <= offered and "volume_set" not in offered
    assert "buy milk, call mom" in first["messages"][-1]["content"]  # the user's own words travel
    assert not [e for e, _ in laptop.inbox if e == "approval.request"]  # T4: reviewer allowed it


async def test_delete_downloads_asks_and_deny_deletes_nothing(
    brain: Brain, laptop: FakeDevice
) -> None:
    """PHASES R2: "Delete everything in Downloads" → approval required; deny → nothing deleted."""
    assert brain.groq is not None
    brain.groq.queue(delegate("Delete everything in Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_delete", path="Downloads/*")]),
        Turn(text=["Okay, I left your Downloads alone."]),
        model="agent",
    )
    sid, _ = await laptop.say("delete everything in downloads")
    await laptop.reply(sid)
    req = await laptop.next("approval.request")
    assert (req["tool"], req["risk"], req["inputs_preview"]) == (
        "file_delete",
        "destructive",
        {"path": "Downloads/*"},
    )
    assert req["options"] == ["allow", "always", "deny"]
    heads_up = await laptop.reply(sid)
    assert spoken(heads_up) == ["Heads up, this will delete everything in Downloads. Go ahead?"]
    assert heads_up[0]["tone"] == "serious"
    ack = await laptop.call(
        "approval.response", {"approval_id": req["approval_id"], "decision": "deny"}
    )
    assert ack["data"] == {"accepted": True}
    assert spoken(await laptop.reply(sid)) == ["Okay, I left your Downloads alone."]
    assert tool_calls(laptop, "file_delete") == []  # the device never got it
    [approval] = await rows(brain, Approval)
    assert approval.decision == "deny" and str(approval.decided_by_device) == laptop.device_id
    [step] = await rows(brain, JobStep)
    assert step.status == "denied"
    told = brain.groq.for_model("agent")[1]["messages"][-1]
    assert told["content"] == "ERROR: The user said no, so it wasn't done. Don't retry it."


async def _hung_job(brain: Brain, laptop: FakeDevice) -> tuple[str, dict[str, Any]]:
    assert brain.groq is not None
    brain.groq.queue(delegate("Find my tax PDFs"))
    brain.groq.queue(
        Turn(tool_calls=[tool("todo_write", items=[{"text": "Search"}, {"text": "Report"}])]),
        Turn(tool_calls=[tool("file_search", path="Documents", query="tax")]),
        Turn(text=["Found nothing for tax in Documents."]),
        model="agent",
    )
    laptop.tools["file_search"] = lambda inp: None  # never answers
    sid, _ = await laptop.say("find my tax pdfs")
    await laptop.reply(sid)
    return sid, await laptop.next("tool.call")


async def test_stop_mid_job_cancels_within_500ms(brain: Brain, laptop: FakeDevice) -> None:
    """PHASES R2: "Stop" mid-job cancels within 500 ms (tier 0 sends interrupt scope "all")."""
    _, call = await _hung_job(brain, laptop)
    t0 = time.monotonic()
    ack = await laptop.call("signal.interrupt", {"scope": "all"})
    assert ack["ok"] is True
    cancel = await laptop.next("tool.cancel")
    await updates(laptop, ("cancelled",))
    assert time.monotonic() - t0 < 0.5
    assert cancel["call_id"] == call["call_id"]
    [job] = await rows(brain, Job)
    assert job.status == "cancelled" and job.finished_at is not None
    assert not brain.voice.jobs.active and not brain.voice.sup.watches


async def test_stop_said_to_the_brain_cancels_the_job(brain: Brain, laptop: FakeDevice) -> None:
    await _hung_job(brain, laptop)
    sid, ack = await laptop.say("stop")
    assert ack["data"]["tier"] == 1
    await updates(laptop, ("cancelled",))
    assert spoken(await laptop.reply(sid))[0] in {
        "On it.",
        "Got it.",
        "Sure thing.",
        "Yep.",
        "You got it.",
    }


async def test_barge_in_stops_speech_not_the_job(brain: Brain, laptop: FakeDevice) -> None:
    await _hung_job(brain, laptop)
    ack = await laptop.call("signal.interrupt", {})
    assert ack["ok"] is True
    assert [j.status for j in brain.voice.jobs.active.values()] == ["running"]


async def test_ra3_how_is_it_going_answers_from_job_state(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    await _hung_job(brain, laptop)
    asked = len(brain.groq.for_model("fast"))
    sid, ack = await laptop.say("how's it going?")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid)) == ["0 of 2 done. Working on: file search."]
    assert len(brain.groq.for_model("fast")) == asked  # no LLM call


async def test_how_is_it_going_without_a_job_is_conversation(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Pretty good, thanks."]))
    sid, ack = await laptop.say("how's it going")
    assert ack["data"]["tier"] == 2
    assert spoken(await laptop.reply(sid)) == ["Pretty good, thanks."]


async def test_steer_use_the_d_drive_reaches_the_running_job(
    brain: Brain, laptop: FakeDevice
) -> None:
    """PHASES R2: "use the D drive instead" steers the running job (§6.4)."""
    assert brain.groq is not None
    brain.groq.queue(delegate("Find room for a backup of my notes on the C drive"))
    brain.groq.queue(
        Turn(
            text=["Switching to the D drive."],
            tool_calls=[tool("job_steer", message="use the D drive instead")],
        )
    )
    brain.groq.queue(
        Turn(tool_calls=[tool("file_list", path="C:/Backups")]),
        Turn(tool_calls=[tool("file_list", path="D:/Backups")]),
        Turn(text=["The D drive works, the backup folder is empty and ready."]),
        model="agent",
    )
    laptop.tools["file_list"] = lambda inp: {
        "ok": True,
        "output": {"path": inp["path"], "items": []},
    }
    gate = asyncio.Event()
    laptop.before_result = gate.wait
    sid, _ = await laptop.say("find room for a backup of my notes on the c drive")
    await laptop.reply(sid)
    await until(lambda: tool_calls(laptop, "file_list"))
    sid2, ack = await laptop.say("use the D drive instead")
    assert ack["data"]["tier"] == 2
    assert spoken(await laptop.reply(sid2)) == ["Switching to the D drive."]
    router = brain.groq.for_model("fast")[1]
    assert {"job_steer", "job_cancel"} <= {t["function"]["name"] for t in router["tools"]}
    assert "running job: Find room for a backup" in router["messages"][-1]["content"]
    gate.set()
    await updates(laptop)
    second = brain.groq.for_model("agent")[1]["messages"]
    assert second[-1] == {
        "role": "user",
        "content": "(The user just said: use the D drive instead)",
    }
    assert [c["input"]["path"] for c in tool_calls(laptop, "file_list")] == [
        "C:/Backups",
        "D:/Backups",
    ]


async def test_t1_three_reads_run_in_parallel_in_one_turn(brain: Brain, laptop: FakeDevice) -> None:
    """T1 + PHASES R2: one model turn, three concurrent tool calls, one result message."""
    assert brain.groq is not None
    brain.groq.queue(delegate("Compare a.txt, b.txt and c.txt on my desktop"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_read", path=f"Desktop/{n}.txt") for n in "abc"]),
        Turn(text=["All three say the same thing."]),
        model="agent",
    )
    laptop.tools["file_read"] = lambda inp: {
        "ok": True,
        "output": {"path": inp["path"], "text": "same"},
    }
    gate = asyncio.Event()
    laptop.before_result = gate.wait
    sid, _ = await laptop.say("compare a b and c on my desktop")
    await laptop.reply(sid)
    await until(lambda: len(tool_calls(laptop, "file_read")) == 3)  # all out before any answer
    gate.set()
    await updates(laptop)
    msgs = brain.groq.for_model("agent")[1]["messages"]
    assert [m["role"] for m in msgs[-4:]] == ["assistant", "tool", "tool", "tool"]
    assert len(msgs[-4]["tool_calls"]) == 3


async def test_t2_malformed_twice_escalates_with_the_same_history(
    brain: Brain, laptop: FakeDevice
) -> None:
    """T2 + PHASES R2: the job finishes on the next chain entry."""
    assert brain.groq is not None and brain.mistral is not None
    brain.groq.queue(delegate("What's in my Downloads folder?"))
    bad = Turn(tool_calls=[tool("file_list", path="Downloads")], malformed=True)
    brain.groq.queue(bad, bad, model="agent")
    brain.mistral.queue(
        Turn(tool_calls=[tool("file_list", path="Downloads")]),
        Turn(text=["Downloads has two files."]),
        model="agent-b",
    )
    items = [{"name": "a.pdf", "type": "file"}, {"name": "b.zip", "type": "file"}]
    laptop.tools["file_list"] = {"ok": True, "output": {"path": "Downloads", "items": items}}
    sid, _ = await laptop.say("what's in my downloads folder")
    await laptop.reply(sid)
    assert (await updates(laptop))[-1]["status"] == "done"
    assert spoken(await laptop.reply(sid)) == ["Downloads has two files."]
    tried, took_over = brain.groq.for_model("agent"), brain.mistral.for_model("agent-b")
    assert (
        len(tried) == 2 and tried[0]["messages"] == tried[1]["messages"] == took_over[0]["messages"]
    )
    [inc] = [i for i in await rows(brain, Incident) if i.stage == "llm"]
    assert (inc.engine_or_provider, inc.remedy) == ("groq/agent", "switch")


async def test_t3_deny_rules_win_and_bare_denies_hide_tools(
    brain: Brain, laptop: FakeDevice
) -> None:
    """T3: a broad deny beats a narrow allow; a bare-tool deny removes it from the model."""
    assert brain.groq is not None
    auth = brain.auth({"access_token": laptop.access_token})
    for rule in (
        {"tool": "shell_run", "decision": "deny"},
        {"tool": "volume_set", "decision": "deny"},
        {"tool": "file_delete", "pattern": "C:/Users/*/Downloads/**", "decision": "deny"},
        {
            "tool": "file_delete",
            "pattern": "C:\\Users\\asha\\Downloads\\a.txt",
            "decision": "allow",
        },
    ):
        r = await brain.client.post("/v2/permissions/rules", json=rule, headers=auth)
        assert r.status_code == 200, r.text
    brain.groq.queue(delegate("Run a command to delete a.txt in Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_delete", path="C:/Users/asha/Downloads/a.txt")]),
        Turn(text=["Your rules block deleting that, so I left it."]),
        model="agent",
    )
    sid, _ = await laptop.say("run a command to delete a.txt in my downloads")
    await laptop.reply(sid)
    await updates(laptop)
    assert tool_calls(laptop, "file_delete") == [] and not [
        e for e, _ in laptop.inbox if e == "approval.request"
    ]
    [step] = await rows(brain, JobStep)
    assert step.status == "denied"
    agent_tools = {t["function"]["name"] for t in brain.groq.for_model("agent")[0]["tools"]}
    assert "shell_run" not in agent_tools and "file_delete" in agent_tools
    reflex_tools = {t["function"]["name"] for t in brain.groq.for_model("fast")[0]["tools"]}
    assert "volume_set" not in reflex_tools and "volume_change" in reflex_tools


async def test_t4_reviewer_escalates_a_call_that_doesnt_match_the_request(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    startup = "C:/Users/asha/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/run.bat"
    brain.groq.queue(delegate("Read my notes on the desktop"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_write", path=startup, content="calc.exe")]),
        Turn(text=["I stopped before changing anything."]),
        model="agent",
    )
    brain.groq.queue(Turn(text=["ASK"]), model="review")
    sid, _ = await laptop.say("read my notes on the desktop")
    await laptop.reply(sid)
    req = await laptop.next("approval.request")
    assert req["tool"] == "file_write" and req["inputs_preview"]["path"] == startup
    review = brain.groq.for_model("review")[0]["messages"][-1]["content"]
    assert "Read my notes" in review and "run.bat" in review
    await laptop.call("approval.response", {"approval_id": req["approval_id"], "decision": "deny"})
    await updates(laptop)
    assert tool_calls(laptop, "file_write") == []


async def test_s2_tool_timeout_replans_and_the_job_finishes(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("List my Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_list", path="Downloads")]),
        Turn(text=["Your laptop didn't answer in time, so I couldn't list it. Try me again?"]),
        model="agent",
    )
    laptop.tools["file_list"] = lambda inp: None
    sid, _ = await laptop.say("list my downloads")
    await laptop.reply(sid)
    call = await laptop.next("tool.call")
    cancel = await drive(brain.clock, laptop.next("tool.cancel", within=10), step=0.25)
    assert cancel["call_id"] == call["call_id"]
    seen = await updates(laptop)  # the timeout has fired: the rest needs no simulated time
    assert seen[-1]["status"] == "done"
    told = brain.groq.for_model("agent")[1]["messages"][-1]["content"]
    assert told == "ERROR: The device didn't finish file_list within 5s."


async def test_s4_same_call_three_times_ends_explained(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Find my resume"))
    same = Turn(tool_calls=[tool("file_list", path="Documents")])
    brain.groq.queue(
        same,
        same,
        same,
        Turn(text=["I kept getting the same list, so I stopped. Want me to look somewhere else?"]),
        model="agent",
    )
    laptop.tools["file_list"] = {"ok": True, "output": {"path": "Documents", "items": []}}
    sid, _ = await laptop.say("find my resume")
    await laptop.reply(sid)
    assert (await updates(laptop))[-1]["status"] == "failed"
    wrap = await laptop.reply(sid)
    assert spoken(wrap)[0] == "I kept getting the same list, so I stopped."
    assert all(d["tone"] == "serious" for d in wrap if d["speak"])
    assert len(tool_calls(laptop, "file_list")) == 2  # the third never ran
    assert "tools" not in brain.groq.for_model("agent")[-1]  # the wrap-up turn can't call tools


async def test_s5_grounding_blocks_an_invented_event(brain: Brain, laptop: FakeDevice) -> None:
    """S5 (the v1 calendar bug): a summary naming an event no tool returned isn't spoken."""
    assert brain.groq is not None
    brain.groq.queue(delegate("What's on my list for today?"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_read", path="Desktop/today.txt")]),
        Turn(text=["You've got Standup at 10am and Dentist at 3pm."]),
        Turn(text=["You've got Standup at 10am."]),
        model="agent",
    )
    laptop.tools["file_read"] = {
        "ok": True,
        "output": {"path": "Desktop/today.txt", "text": "Standup at 10am"},
    }
    sid, _ = await laptop.say("what's on my list for today")
    await laptop.reply(sid)
    await updates(laptop)
    assert spoken(await laptop.reply(sid)) == ["You've got Standup at 10am."]
    fix = brain.groq.for_model("agent")[2]
    assert "tools" not in fix and "Dentist" in fix["messages"][-1]["content"]
    [inc] = await rows(brain, Incident)
    assert (inc.stage, inc.remedy) == ("grounding", "replan")


async def test_s7_job_twice_over_its_estimate_gets_a_new_one(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Find my tax PDFs"))
    brain.groq.queue(
        Turn(
            tool_calls=[tool("todo_write", items=[{"text": "Search"}, {"text": "Report"}], eta_s=5)]
        ),
        Turn(tool_calls=[tool("file_search", path="Documents", query="tax")]),
        Turn(text=["Found nothing for tax in Documents."]),
        model="agent",
    )
    laptop.tools["file_search"] = {"ok": True, "output": {"matches": []}}
    laptop.before_result = lambda: brain.clock.sleep(18)
    sid, _ = await laptop.say("find my tax pdfs")
    await laptop.reply(sid)
    seen = await drive(brain.clock, updates(laptop, within=10), step=0.05, limit_s=60)
    [note] = [u for u in seen if u.get("note", "").startswith("This is taking longer")]
    assert note["eta_s"] >= 10
    assert spoken(await laptop.reply(sid))[0] == note["note"]  # said out loud, once


async def test_ra4_yes_do_it_resolves_the_pending_approval(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Delete old.zip from Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_delete", path="Downloads/old.zip")]),
        Turn(text=["Deleted old.zip from your Downloads."]),
        model="agent",
    )
    laptop.tools["file_delete"] = {"ok": True, "output": {"deleted": 1}}
    sid, _ = await laptop.say("delete old.zip from downloads")
    await laptop.reply(sid)
    await laptop.next("approval.request")
    await laptop.reply(sid)  # "Heads up…"
    asked = len(brain.groq.for_model("fast"))
    sid2, ack = await laptop.say("yes, do it")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid2))[0] in {
        "On it.",
        "Got it.",
        "Sure thing.",
        "Yep.",
        "You got it.",
    }
    assert (await updates(laptop))[-1]["status"] == "done"
    assert len(tool_calls(laptop, "file_delete")) == 1
    assert len(brain.groq.for_model("fast")) == asked  # no LLM call
    [approval] = await rows(brain, Approval)
    assert approval.decision == "allow"


async def test_approvals_reach_every_device_and_the_first_answer_wins(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    phone = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Pixel"))
    await phone.connect()
    try:
        await phone.hello(capabilities=["apps", "media", "sms"])
        brain.groq.queue(delegate("Delete old.zip from Downloads"))
        brain.groq.queue(
            Turn(tool_calls=[tool("file_delete", path="Downloads/old.zip")]),
            Turn(text=["Deleted old.zip from your Downloads."]),
            model="agent",
        )
        laptop.tools["file_delete"] = {"ok": True, "output": {"deleted": 1}}
        sid, _ = await laptop.say("delete old.zip from downloads")
        await laptop.reply(sid)
        on_laptop, on_phone = (
            await laptop.next("approval.request"),
            await phone.next("approval.request"),
        )
        assert on_laptop["approval_id"] == on_phone["approval_id"]
        aid = on_phone["approval_id"]
        first = await phone.call("approval.response", {"approval_id": aid, "decision": "allow"})
        late = await laptop.call("approval.response", {"approval_id": aid, "decision": "deny"})
        assert (first["data"], late["data"]) == ({"accepted": True}, {"accepted": False})
        for dev in (laptop, phone):
            resolved = await dev.next("approval.resolved")
            assert (resolved["decision"], resolved["by_device"]) == ("allow", phone.device_id)
        await updates(laptop)
        assert len(tool_calls(laptop, "file_delete")) == 1  # ran on the origin
    finally:
        await phone.close()


async def test_plan_approval_covers_its_exact_steps(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Empty my Downloads folder"))
    steps = [{"tool": "file_delete", "target": "Downloads/*", "why": "you asked"}]
    brain.groq.queue(
        Turn(tool_calls=[tool("plan_submit", summary="Empty your Downloads folder", steps=steps)]),
        Turn(tool_calls=[tool("file_delete", path="Downloads/*")]),
        Turn(text=["Downloads is empty now."]),
        model="agent",
    )
    laptop.tools["file_delete"] = {"ok": True, "output": {"deleted": 14}}
    sid, _ = await laptop.say("empty my downloads folder")
    await laptop.reply(sid)
    plan = await laptop.next("approval.request")
    assert (plan["tool"], plan["options"]) == ("plan", ["allow", "deny"])
    assert plan["inputs_preview"]["steps"][0]["target"] == "Downloads/*"
    await laptop.call(
        "approval.response", {"approval_id": plan["approval_id"], "decision": "allow"}
    )
    await updates(laptop)
    assert len(tool_calls(laptop, "file_delete")) == 1
    assert [a.tool for a in await rows(brain, Approval)] == ["plan"]  # no second ask


async def test_always_allow_adds_a_rule_and_stops_asking(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Delete old.zip from Downloads, twice to be sure"))
    again = Turn(tool_calls=[tool("file_delete", path="Downloads/old.zip")])
    brain.groq.queue(
        again, again, Turn(text=["Deleted old.zip from your Downloads."]), model="agent"
    )
    laptop.tools["file_delete"] = {"ok": True, "output": {"deleted": 1}}
    sid, _ = await laptop.say("delete old.zip from downloads")
    await laptop.reply(sid)
    req = await laptop.next("approval.request")
    await laptop.call(
        "approval.response", {"approval_id": req["approval_id"], "decision": "always"}
    )
    await updates(laptop)
    assert len(tool_calls(laptop, "file_delete")) == 2
    assert len(await rows(brain, Approval)) == 1
    [rule] = await rows(brain, PermissionRule)
    assert (rule.tool, rule.pattern, rule.decision) == ("file_delete", "Downloads/old.zip", "allow")


async def test_ask_user_question_is_answered_by_voice(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Make a shopping list file"))
    brain.groq.queue(
        Turn(
            tool_calls=[
                tool("ask_user", question="Desktop or Documents?", options=["Desktop", "Documents"])
            ]
        ),
        Turn(text=["Okay, I'll use your desktop."]),
        model="agent",
    )
    sid, _ = await laptop.say("make a shopping list file")
    await laptop.reply(sid)
    ask = await laptop.next("ask.request")
    assert (ask["question"], ask["options"]) == ("Desktop or Documents?", ["Desktop", "Documents"])
    assert spoken(await laptop.reply(sid)) == ["Desktop or Documents?"]
    sid2, ack = await laptop.say("the desktop")
    assert ack["data"]["tier"] == 1
    await laptop.reply(sid2)
    await updates(laptop)
    told = brain.groq.for_model("agent")[1]["messages"][-1]["content"]
    assert told == "The user answered: the desktop"
    assert (await laptop.next("ask.resolved"))["answer"] == "the desktop"


async def test_ps3_wrap_up_is_three_sentences_and_the_rest_is_an_artifact(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("Organize my Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("folder_organize", path="Downloads")]),
        Turn(
            text=[
                "Done. I sorted twelve files. Four went to Images. Three went to Documents. "
                "Five went to Other. Want me to undo it?"
            ]
        ),
        model="agent",
    )
    brain.groq.queue(Turn(text=["ALLOW"]), model="review")
    laptop.tools["folder_organize"] = {
        "ok": True,
        "output": {"moved": {"Images": 4, "Documents": 3, "Other": 5}},
    }
    sid, _ = await laptop.say("organize my downloads")
    await laptop.reply(sid)
    art = await laptop.next("artifact.new")
    done = (await updates(laptop))[-1]
    assert spoken(await laptop.reply(sid)) == [
        "Done.",
        "I sorted twelve files.",
        "Four went to Images.",
    ]
    assert done["artifact_id"] == art["artifact_id"] and art["kind"] == "text"
    [row] = await rows(brain, Artifact)
    assert row.preview["text"].endswith("Want me to undo it?")
    assert done["summary"].count(".") == 5


async def test_d1_invoice_email_saved_to_downloads(
    brain: Brain, laptop: FakeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1 with stub Gmail tools (real Gmail lands in R4): brain tools → a device write on the
    origin; steps persisted; the summary only names what tools returned."""
    from pydantic import BaseModel, ConfigDict

    class Query(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str

    class MessageRef(BaseModel):
        model_config = ConfigDict(extra="forbid")
        message_id: str

    async def search(call: Any, inp: dict[str, Any]) -> Any:
        return [
            {"id": "m-77", "from": "Daraz", "subject": "Invoice INV-2041", "date": "2026-10-08"}
        ]

    async def attachment(call: Any, inp: dict[str, Any]) -> Any:
        assert inp == {"message_id": "m-77"}
        return {"name": "INV-2041.pdf", "content_base64": "JVBERi0xLjQ="}

    stubs = [
        ToolSpec(
            "gmail_search",
            "Searches Gmail.",
            Query,
            "brain",
            Risk.READ,
            handler=search,
            keywords="email invoice mail",
        ),
        ToolSpec(
            "gmail_get_attachment",
            "Gets an email's attachment.",
            MessageRef,
            "brain",
            Risk.READ,
            handler=attachment,
            keywords="attachment pdf invoice email",
        ),
    ]
    monkeypatch.setattr(registry, "INTEGRATIONS", stubs)
    for i, spec in enumerate(stubs):
        monkeypatch.setitem(registry.BY_NAME, spec.name, spec)
        monkeypatch.setitem(registry.ORDER, spec.name, 900 + i)
    assert brain.groq is not None
    brain.groq.queue(delegate("Find my last invoice email and save the PDF to Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("gmail_search", query="invoice")]),
        Turn(tool_calls=[tool("gmail_get_attachment", message_id="m-77")]),
        Turn(
            tool_calls=[
                tool(
                    "file_write",
                    path="Downloads/INV-2041.pdf",
                    content="JVBERi0xLjQ=",
                    encoding="base64",
                )
            ]
        ),
        Turn(text=["Saved the Daraz invoice INV-2041 to your Downloads."]),
        model="agent",
    )
    brain.groq.queue(Turn(text=["ALLOW"]), model="review")
    laptop.tools["file_write"] = {
        "ok": True,
        "output": {"path": "C:/Users/asha/Downloads/INV-2041.pdf"},
    }
    sid, _ = await laptop.say("find my last invoice email and save the pdf to downloads")
    await laptop.reply(sid)
    await updates(laptop)
    assert spoken(await laptop.reply(sid)) == [
        "Saved the Daraz invoice INV-2041 to your Downloads."
    ]
    steps = sorted(await rows(brain, JobStep), key=lambda s: s.started_at)
    assert [(s.tool, s.status) for s in steps] == [
        ("gmail_search", "ok"),
        ("gmail_get_attachment", "ok"),
        ("file_write", "ok"),
    ]
    assert steps[0].device_id is None and str(steps[2].device_id) == laptop.device_id
    [write] = tool_calls(laptop, "file_write")
    assert write["input"]["encoding"] == "base64"


async def test_restart_fails_running_jobs_with_an_explanation(
    brain: Brain, laptop: FakeDevice
) -> None:
    async with brain.rt.db() as db:
        from app.db.models import Device

        device = await db.get_one(Device, __import__("uuid").UUID(laptop.device_id))
        db.add(Job(user_id=device.user_id, title="Organize Downloads", status="running"))
        await db.commit()
    await brain.voice.jobs.fail_stale()
    update = await laptop.next("job.update")
    assert (update["status"], update["title"]) == ("failed", "Organize Downloads")
    [job] = await rows(brain, Job)
    assert job.status == "failed" and "restarted" in (job.summary or "")


async def test_jobs_routes_show_steps_and_keep_users_apart(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(delegate("List my Downloads"))
    brain.groq.queue(
        Turn(tool_calls=[tool("file_list", path="Downloads")]),
        Turn(text=["Downloads is empty."]),
        model="agent",
    )
    laptop.tools["file_list"] = {"ok": True, "output": {"path": "Downloads", "items": []}}
    sid, _ = await laptop.say("list my downloads")
    await laptop.reply(sid)
    job_id = (await updates(laptop))[-1]["job_id"]
    auth = brain.auth({"access_token": laptop.access_token})
    r = await brain.client.get("/v2/jobs", headers=auth)
    [item] = r.json()["data"]["items"]
    assert (item["id"], item["status"], item["summary"]) == (job_id, "done", "Downloads is empty.")
    r = await brain.client.get(f"/v2/jobs/{job_id}", headers=auth)
    [step] = r.json()["data"]["steps"]
    assert (step["tool"], step["status"], step["input"]) == (
        "file_list",
        "ok",
        {"path": "Downloads", "pattern": "*", "recursive": False, "limit": 200},
    )
    ben = brain.auth(await brain.sign_in("ben@example.com", "Ben"))
    assert (await brain.client.get(f"/v2/jobs/{job_id}", headers=ben)).status_code == 404
    assert (await brain.client.post(f"/v2/jobs/{job_id}/cancel", headers=ben)).status_code == 404
    assert (await brain.client.get("/v2/jobs", headers=ben)).json()["data"]["items"] == []


async def test_cancel_route_stops_a_running_job(brain: Brain, laptop: FakeDevice) -> None:
    await _hung_job(brain, laptop)
    [job_id] = [str(j) for j in brain.voice.jobs.active]
    auth = brain.auth({"access_token": laptop.access_token})
    r = await brain.client.post(f"/v2/jobs/{job_id}/cancel", headers=auth)
    assert r.json()["data"] == {"status": "cancelled"}
    await updates(laptop, ("cancelled",))
    r = await brain.client.post(f"/v2/jobs/{job_id}/cancel", headers=auth)
    assert r.json()["data"] == {"status": "cancelled"}  # already over: unchanged


async def test_permission_rules_routes(brain: Brain, laptop: FakeDevice) -> None:
    auth = brain.auth({"access_token": laptop.access_token})
    r = await brain.client.post(
        "/v2/permissions/rules", json={"tool": "nope_tool", "decision": "deny"}, headers=auth
    )
    assert r.status_code == 422
    r = await brain.client.post(
        "/v2/permissions/rules",
        json={"tool": "shell_run", "pattern": "git status*", "decision": "allow"},
        headers=auth,
    )
    rule_id = r.json()["data"]["id"]
    [item] = (await brain.client.get("/v2/permissions/rules", headers=auth)).json()["data"]["items"]
    assert (item["tool"], item["pattern"], item["decision"]) == (
        "shell_run",
        "git status*",
        "allow",
    )
    ben = brain.auth(await brain.sign_in("ben@example.com", "Ben"))
    assert (
        await brain.client.delete(f"/v2/permissions/rules/{rule_id}", headers=ben)
    ).status_code == 404
    assert (await brain.client.get("/v2/permissions/rules", headers=ben)).json()["data"][
        "items"
    ] == []
    r = await brain.client.post(
        "/v2/permissions/rules",
        json={"tool": "shell_run", "decision": "deny", "device_id": laptop.device_id},
        headers=ben,
    )
    assert r.status_code == 404  # not Ben's device
    assert (
        await brain.client.delete(f"/v2/permissions/rules/{rule_id}", headers=auth)
    ).status_code == 200
    tools = (await brain.client.get("/v2/capabilities/tools", headers=auth)).json()["data"]["items"]
    by_name = {t["name"]: t for t in tools}
    assert (by_name["file_delete"]["risk"], by_name["file_delete"]["permission"]) == (
        "destructive",
        "ask",
    )
    assert by_name["file_read"]["permission"] == "allow"
    assert by_name["file_write"]["permission"] == "review"


async def test_engines_chains_show_free_first_without_keys(
    brain: Brain, laptop: FakeDevice
) -> None:
    auth = brain.auth({"access_token": laptop.access_token})
    roles = (await brain.client.get("/v2/engines/chains", headers=auth)).json()["data"]["roles"]
    agent = roles["agent"]
    assert [(e["provider"], e["model"]) for e in agent] == [
        ("groq", "agent"),
        ("mistral", "agent-b"),
    ]
    assert agent[0] == agent[0] | {"keys": 1, "enabled": True, "healthy": True, "paid": False}
    assert "gk-test" not in str(roles)  # keys never leave the brain
