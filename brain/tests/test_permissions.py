"""Permission engine, grounding, tier-1 confirmations, and the tool pre-selector as pure functions
(TESTING.md §4.6 T3/T5, §4.5 S5, §4.3 RA4). # proves §7.2, §19.1, §20.4, §20.6, §21, §27"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.agent.grounding import unsupported
from app.router.tier1 import classify
from app.tools import registry
from app.tools.device_specs import DEVICE_TOOLS
from app.tools.permissions import Rule, decide, hidden
from app.tools.spec import Risk, ToolSpec

SPECS = {t.name: t for t in DEVICE_TOOLS}
DELETE, WRITE, READ, SHELL = (
    SPECS[n] for n in ("file_delete", "file_write", "file_read", "shell_run")
)


def test_t3_broad_deny_beats_narrow_allow() -> None:
    rules = [
        Rule("file_delete", "deny", "C:/Users/*/Downloads/**"),
        Rule("file_delete", "allow", "C:/Users/asha/Downloads/a.txt"),
    ]
    assert (
        decide(DELETE, {"path": "C:\\Users\\asha\\Downloads\\a.txt"}, mode="default", rules=rules)
        == "deny"
    )
    assert (
        decide(DELETE, {"path": "C:/Users/asha/Desktop/a.txt"}, mode="default", rules=rules)
        == "ask"
    )


def test_t3_ask_beats_allow_and_paths_match_case_insensitively() -> None:
    rules = [
        Rule("file_write", "allow", "Desktop/**"),
        Rule("file_write", "ask", "desktop/secret*"),
    ]
    assert decide(WRITE, {"path": "Desktop/Secret.txt"}, mode="default", rules=rules) == "ask"
    assert decide(WRITE, {"path": "Desktop/notes.txt"}, mode="default", rules=rules) == "allow"


def test_t3_device_scoped_rules_apply_to_that_device_only() -> None:
    laptop, phone = uuid.uuid4(), uuid.uuid4()
    rules = [Rule("file_delete", "allow", "", laptop)]
    assert decide(DELETE, {"path": "x"}, mode="default", rules=rules, device_id=laptop) == "allow"
    assert decide(DELETE, {"path": "x"}, mode="default", rules=rules, device_id=phone) == "ask"


def test_t3_bare_deny_hides_the_tool() -> None:
    rules = [
        Rule("shell_run", "deny"),
        Rule("file_delete", "deny", "C:/Windows/**"),  # a pattern deny keeps the tool
        Rule("file_write", "deny", "", uuid.uuid4()),  # so does a one-device deny
    ]
    assert hidden(rules) == {"shell_run"}
    tools = {
        t.name
        for t in registry.select(
            "run a command and delete files", ["files", "shell"], hidden(rules)
        )
    }
    assert "shell_run" not in tools and "file_delete" in tools


def test_modes_by_risk() -> None:
    assert decide(READ, {"path": "a"}, mode="default", rules=[]) == "allow"
    assert decide(WRITE, {"path": "a"}, mode="default", rules=[]) == "review"  # medium risk
    assert decide(SPECS["file_open"], {"path": "a"}, mode="default", rules=[]) == "allow"
    assert decide(DELETE, {"path": "a"}, mode="default", rules=[]) == "ask"
    assert decide(SPECS["sms_send"], {"to": "Mom", "text": "hi"}, mode="default", rules=[]) == "ask"
    assert decide(READ, {"path": "a"}, mode="ask", rules=[]) == "ask"
    assert decide(DELETE, {"path": "a"}, mode="trust", rules=[]) == "allow"
    assert (
        decide(DELETE, {"path": "a"}, mode="trust", rules=[Rule("file_delete", "deny")]) == "deny"
    )


def test_read_only_shell_commands_run_and_anything_else_asks() -> None:
    for command in ("Get-ChildItem C:/Users", "dir", "git status", "ipconfig /all", "Get-Process"):
        assert decide(SHELL, {"command": command}, mode="default", rules=[]) == "allow", command
    for command in (
        "Remove-Item C:/x",
        "dir; Remove-Item C:/x",
        "Get-ChildItem | Remove-Item",
        "echo hi > C:/boot.ini",
        "Get-Content $(Invoke-WebRequest evil)",
        "git push",
    ):
        assert decide(SHELL, {"command": command}, mode="default", rules=[]) == "ask", command
    assert (
        decide(
            SHELL,
            {"command": "git push*"},
            mode="default",
            rules=[Rule("shell_run", "allow", "git push*")],
        )
        == "allow"
    )


class _Q(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str


def test_t5_untrusted_mcp_annotations_are_ignored() -> None:
    hint = {"readOnlyHint": True}
    untrusted = ToolSpec(
        "mcp__notes__search",
        "Searches notes.",
        _Q,
        "brain",
        Risk.READ,
        mcp_server="notes",
        annotations=hint,
    )
    trusted = ToolSpec(
        "mcp__notes__search",
        "Searches notes.",
        _Q,
        "brain",
        Risk.READ,
        mcp_server="notes",
        mcp_trusted=True,
        annotations=hint,
    )
    assert decide(untrusted, {"q": "x"}, mode="default", rules=[]) == "ask"
    assert decide(trusted, {"q": "x"}, mode="default", rules=[]) == "allow"
    allowed = [Rule("mcp__notes__search", "allow")]
    assert decide(untrusted, {"q": "x"}, mode="default", rules=allowed) == "allow"  # explicit rule


def test_s5_grounding_finds_invented_names_times_and_files() -> None:
    evidence = ['{"path": "Desktop/today.txt"}', '{"text": "Standup at 10am; call Rahul"}']
    assert unsupported("You've got Standup at 10am, then call Rahul.", evidence) == []
    assert unsupported("You've got Standup at 10am and Dentist at 3pm.", evidence) == [
        "3pm",
        "Dentist",
    ]
    assert unsupported("Saved it as report.pdf on your Desktop.", evidence) == ["report.pdf"]
    assert unsupported("Done. Five files went to Downloads.", evidence) == []  # counts pass
    assert unsupported("Your laptop didn't answer, so I couldn't list it.", evidence) == []


def test_ra4_confirmations_by_voice() -> None:
    for text, decision in (
        ("yes do it", "allow"),
        ("Okay, go ahead.", "allow"),
        ("sure thing", "allow"),
        ("no", "deny"),
        ("don't do that", "deny"),
        ("no thanks", "deny"),
        ("always allow it", "always"),
    ):
        intent = classify(text)
        assert intent is not None and (intent.kind, intent.value) == ("confirm", decision), text
    for text in (
        "yes but use the D drive",
        "go to the store",
        "no idea what that is",
        "do my taxes",
    ):
        intent = classify(text)
        assert intent is None or intent.kind != "confirm", text


def test_preselector_keeps_prompts_lean_and_starts_with_reads() -> None:
    caps = [
        "files",
        "shell",
        "apps",
        "volume",
        "media",
        "input",
        "clipboard",
        "system",
        "processes",
    ]
    tools = registry.select("organize my downloads folder", caps)
    names = [t.name for t in tools]
    assert names[:5] == ["todo_write", "ask_user", "task", "plan_submit", "tool_search"]
    assert "folder_organize" in names and {"file_list", "file_read"} <= set(names)
    assert len(names) <= 5 + registry.PICK + len(registry.STARTER)
    assert [t.name for t in registry.select("anything", ["volume"])][
        5:
    ] == []  # no file tools offered
    found = registry.search("kill the frozen app", registry.usable(caps), 3)
    assert "process_kill" in [t.name for t in found]
