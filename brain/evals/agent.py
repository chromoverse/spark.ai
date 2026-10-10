"""Live agent eval (TESTING.md §7, REDESIGN §5.5): ~30 multi-step desktop tasks with stubbed tools,
run through the real agent prompt and tool catalog on every agent chain entry that has a key.
Approvals are granted unless a row denies them; ask_user gets the row's answer.

A task passes when the model calls what it must (and nothing forbidden), says what it should,
stays grounded in the tool outputs, and finishes within its turn budget. Also reported: tool-call
validity, malformed turns, parallel calls, turns, tokens, and wrap-ups over 3 sentences.

    cd brain && uv run python -m evals.agent [--limit 5] [--entry groq/openai/gpt-oss-120b]

Never in PR CI: it spends free daily quota (Groq: 1K requests a day per model).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.agent import grounding
from app.agent.loop import SYSTEM
from app.core.config import Settings
from app.llm import openai_compat
from app.llm.chains import CHAINS, providers
from app.llm.types import Done, ProviderError, TextDelta, ToolUse
from app.tools import registry
from app.tools.spec import Risk
from evals.run import persona_misses

EVALS = Path(__file__).resolve().parent
CAPS = [
    "apps", "brightness", "clipboard", "files", "input", "media", "power", "processes", "screen",
    "shell", "system", "volume",
]  # fmt: skip
CONTEXT = "(context: it's Saturday 10 October 2026, 2:05 PM local time; device: Laptop)"
MAX_TURNS = 12  # the real loop allows 24; a good job needs far fewer
ASKS = {Risk.DESTRUCTIVE, Risk.EXTERNAL}


@dataclass
class Run:
    names: list[str] = field(default_factory=list)
    inputs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    calls: int = 0
    valid: int = 0
    malformed: int = 0
    parallel: int = 0  # turns with 2+ calls
    turns: int = 0
    tokens: int = 0
    final: str = ""
    evidence: list[str] = field(default_factory=list)
    denied: set[str] = field(default_factory=set)
    after_deny: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Result:
    label: str
    passed: int = 0
    total: int = 0
    calls: int = 0
    valid: int = 0
    malformed: int = 0
    parallel_ok: int = 0
    parallel_total: int = 0
    turns: list[int] = field(default_factory=list)
    tokens: list[int] = field(default_factory=list)
    long_wrapups: int = 0
    errors: int = 0
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)


# Unlisted lookups find nothing (a bare "done" reads as success and sends the model in circles).
_EMPTY: dict[str, Any] = {
    "file_list": lambda inp: {"path": inp.get("path", ""), "items": []},
    "file_search": lambda inp: {"matches": []},
    "process_list": lambda inp: {"processes": []},
    "app_list": lambda inp: {"apps": []},
}


def _canned(
    row: dict[str, Any], name: str, seen: dict[str, int], inp: dict[str, Any]
) -> dict[str, Any]:
    tools = row.get("tools", {})
    if name not in tools and name in _EMPTY:
        return {"ok": True, "output": _EMPTY[name](inp)}
    answer = tools.get(name, {"ok": True, "output": "done"})
    if isinstance(answer, list):
        i = seen.get(name, 0)
        seen[name] = i + 1
        answer = answer[min(i, len(answer) - 1)]
    return dict(answer)


def _result(use: ToolUse, ok: bool, content: str) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": use.id, "content": content, "is_error": not ok}


def _run_tool(
    row: dict[str, Any], use: ToolUse, run: Run, tools: list[Any], seen: dict[str, int]
) -> dict[str, Any]:
    spec = registry.BY_NAME[use.name]
    run.calls += 1
    run.names.append(use.name)
    run.inputs.append((use.name, use.input))
    if run.denied:
        run.after_deny.append(use.name)
    try:
        inp = spec.input_model.model_validate(use.input).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        return _result(use, False, f"Invalid input for {spec.name}: {first['loc']}: {first['msg']}")
    run.valid += 1
    run.evidence.append(json.dumps(use.input))
    deny = set(row.get("deny", []))
    if spec.name == "todo_write":
        return _result(use, True, "Checklist updated.")
    if spec.name == "ask_user":
        answer = row.get("answer", "whatever you think is best")
        run.evidence.append(answer)
        return _result(use, True, f"The user answered: {answer}")
    if spec.name == "plan_submit":
        if "plan_submit" in deny:
            run.denied.add("plan_submit")
            return _result(
                use, False, "The user said no to the plan. Don't do any of it; wrap up and say so."
            )
        return _result(use, True, "Approved. Go ahead with exactly those steps.")
    if spec.name == "tool_search":
        pool = [t for t in registry.usable(CAPS) if t not in tools]
        found = registry.search(inp["query"], pool, 5)
        tools.extend(found)
        return _result(
            use,
            True,
            "Added: " + "; ".join(t.name for t in found) if found else "Nothing else matches.",
        )
    if spec.name == "task":
        return _result(use, True, "The sub-agent found nothing more.")
    if spec.risk in ASKS and spec.name in deny:
        run.denied.add(spec.name)
        return _result(use, False, "The user said no, so it wasn't done. Don't retry it.")
    answer = _canned(row, spec.name, seen, inp)
    if answer.get("ok"):
        content = json.dumps(answer.get("output", "ok"))
        run.evidence.append(content)
        return _result(use, True, content)
    message = answer.get("error", {}).get("message", f"{spec.name} failed.")
    run.evidence.append(message)
    return _result(use, False, message)


async def run_task(
    http: httpx.AsyncClient,
    base_url: str,
    keys: list[str],
    key_turn: list[int],
    model: str,
    extra: dict[str, Any],
    row: dict[str, Any],
    spacing_s: float,
) -> Run:
    run = Run(evidence=[row["request"], row["task"]])
    tools = registry.select(f"{row['task']} {row['request']}", CAPS)
    text = f'{row["task"]}\n\n(The user\'s words: "{row["request"]}")\n\n{CONTEXT}'
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    seen: dict[str, int] = {}
    retried = False
    while run.turns < MAX_TURNS:
        said, error = "", None
        uses: list[ToolUse] = []
        for _ in keys:
            key_turn[0] += 1
            said, uses = "", []
            try:
                async for ev in openai_compat.stream(
                    http,
                    base_url=base_url,
                    api_key=keys[key_turn[0] % len(keys)],
                    model=model,
                    system=SYSTEM,
                    messages=messages,
                    tools=[t.to_def() for t in tools],
                    max_tokens=2048,
                    extra=extra,
                ):
                    if isinstance(ev, TextDelta):
                        said += ev.text
                    elif isinstance(ev, ToolUse):
                        uses.append(ev)
                    elif isinstance(ev, Done):
                        run.tokens += sum(ev.usage.values())
                error = None
                break
            except ProviderError as exc:
                error = exc
                if exc.kind != "rate_limited":
                    break
        await asyncio.sleep(spacing_s)
        if error is not None:
            if error.kind == "malformed" and not retried:
                run.malformed += 1
                retried = True  # the real loop retries once, then escalates to the next entry
                continue
            if error.kind == "malformed":
                run.malformed += 1
            run.error = error.kind
            return run
        if not uses and not said.strip() and not retried:  # the loop retries an empty turn too
            run.malformed += 1
            retried = True
            continue
        retried = False
        run.turns += 1
        if not uses:
            run.final = said.strip()
            return run
        if len(uses) > 1:
            run.parallel += 1
        results = [_run_tool(row, u, run, tools, seen) for u in uses]
        blocks = [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
        messages += [
            {
                "role": "assistant",
                "content": ([{"type": "text", "text": said}] if said else []) + blocks,
            },
            {"role": "user", "content": results},
        ]
    run.error = "turn budget"
    return run


def grade(row: dict[str, Any], run: Run) -> str | None:
    """None = pass, else the reason."""
    if run.error:
        return run.error
    called = set(run.names)
    if missing := [c for c in row.get("calls", []) if c not in called]:
        return f"never called {missing}"
    if row.get("calls_any") and not called & set(row["calls_any"]):
        return f"called none of {row['calls_any']}"
    if bad := [c for c in row.get("forbid", []) if c in called]:
        return f"called forbidden {bad}"
    if row.get("forbid_after_deny") and [
        n for n in run.after_deny if registry.BY_NAME[n].risk in ASKS
    ]:
        return f"kept going after a no: {run.after_deny}"
    for tool_name, word in row.get("forbid_args", {}).items():
        if any(n == tool_name and word in json.dumps(i) for n, i in run.inputs):
            return f"{tool_name} touched {word!r}"
    if not run.final:
        return "no wrap-up"
    final = grounding.plain(run.final).lower()
    if missing := [m for m in row.get("mentions", []) if m.lower() not in final]:
        return f"wrap-up misses {missing}: {run.final[:80]!r}"
    if row.get("mentions_any") and not any(m.lower() in final for m in row["mentions_any"]):
        return f"wrap-up names none of {row['mentions_any']}: {run.final[:80]!r}"
    if row.get("honest_empty") and not any(
        w in final for w in ("couldn't", "didn't find", "no ", "not find", "nothing", "can't find")
    ):
        return f"didn't say it found nothing: {run.final[:80]!r}"
    if row.get("cant") and not any(
        w in final for w in ("can't", "cannot", "not able", "don't have", "unable", "no way")
    ):
        return f"didn't say it can't: {run.final[:80]!r}"
    if unsupported := grounding.unsupported(run.final, run.evidence):
        return f"ungrounded {unsupported}: {run.final[:80]!r}"
    return None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", help="only this provider/model, e.g. groq/openai/gpt-oss-120b")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--spacing", type=float, default=2.0, help="seconds between calls")
    ap.add_argument("--allow-training", action="store_true")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--verbose", action="store_true", help="print calls and wrap-up of misses")
    args = ap.parse_args()
    settings = Settings()
    rows = [json.loads(line) for line in (EVALS / "agent.jsonl").read_text().splitlines() if line]
    if args.only:
        rows = [r for r in rows if r["id"] in args.only.split(",")]
    if args.limit:
        rows = rows[: args.limit]
    table = providers(settings)
    results: list[Result] = []
    async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(60, connect=5)) as http:
        for entry in CHAINS["agent"]:
            label = f"{entry.provider}/{entry.model}"
            if (args.entry and label != args.entry) or (
                entry.paid and not settings.paid_providers_enabled
            ):
                continue
            if entry.trains_on_data and not args.allow_training:
                continue
            base_url, keys = table.get(entry.provider, ("", []))
            if not keys:
                print(f"skip {label}: no key")
                continue
            print(f"running {label} on {len(rows)} tasks, {len(keys)} key(s)…", flush=True)
            res, key_turn, t0 = Result(label), [0], time.perf_counter()
            for row in rows:
                run = await run_task(
                    http, base_url, keys, key_turn, entry.model, entry.extra, row, args.spacing
                )
                res.total += 1
                res.calls += run.calls
                res.valid += run.valid
                res.malformed += run.malformed
                res.errors += 1 if run.error and run.error != "turn budget" else 0
                if row.get("parallel"):
                    res.parallel_total += 1
                    res.parallel_ok += 1 if run.parallel else 0
                if run.final:
                    res.turns.append(run.turns)
                    res.tokens.append(run.tokens)
                    res.long_wrapups += 1 if persona_misses(run.final) else 0
                if (why := grade(row, run)) is None:
                    res.passed += 1
                else:
                    res.failures.append(f"{row['id']}: {why}")
                print(f"  {row['id']}: {'ok' if why is None else why}", flush=True)
                if why is not None and args.verbose:
                    for name, inp in run.inputs:
                        print(f"      {name} {json.dumps(inp)[:140]}")
                    print(f"      → {run.final[:200]!r}")
            res.seconds = time.perf_counter() - t0
            results.append(res)
    if not results:
        print("No entries ran. Add GROQ_API_KEYS to deploy/.env.")
        return
    print(
        "\n| entry | tasks | valid calls | malformed turns | parallel | turns avg | tokens avg "
        "| wrap-ups off-style | errors |"
    )
    print("|---|---|---|---|---|---|---|---|---|")

    def avg(v: list[int]) -> float:
        return sum(v) / len(v) if v else 0.0

    for r in results:
        print(
            f"| {r.label} | {r.passed}/{r.total} | {r.valid}/{r.calls} | {r.malformed} | "
            f"{r.parallel_ok}/{r.parallel_total} | {avg(r.turns):.1f} | {avg(r.tokens):.0f} | "
            f"{r.long_wrapups} | {r.errors} |"
        )
    for r in results:
        if r.failures:
            print(f"\n{r.label} misses ({len(r.failures)}):")
            for f in r.failures:
                print(f"  - {f}")


if __name__ == "__main__":
    asyncio.run(main())
