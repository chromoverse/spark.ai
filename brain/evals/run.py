"""Live reflex eval (TESTING.md §7, REDESIGN §5.5): runs every reflex chain entry that has a key
against `evals/reflex.jsonl` and reports time to first token, tool-call validity, answers, and
banned phrases. The p95 TTFT gate (400 ms) decides which entries are reflex-grade. Rows may carry
what Spark remembers (`profile` in the system prompt, `remembered` in the note), like real turns.
`--suite memory` grades the memory extractor instead (`evals/memory.jsonl`, the memory chain).

    cd brain && uv run python -m evals.run --suite reflex [--limit 20]
        [--entry groq/openai/gpt-oss-20b]
    cd brain && uv run python -m evals.run --suite memory

Never in PR CI: it calls free providers and spends their daily quota (Groq: 1K requests/day).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.agent import persona, reflex
from app.agent.context import Context
from app.core.config import Settings
from app.llm import openai_compat
from app.llm.chains import CHAINS, providers
from app.llm.types import ProviderError, TextDelta, ToolUse
from app.memory import extract
from app.memory.store import Found

EVALS = Path(__file__).resolve().parent
TTFT_GATE_MS = 400.0
NOW = datetime(2026, 10, 10, 8, 20, tzinfo=UTC)  # Saturday 2:05 PM in Nepal (+5:45)
ALL_CAPS = frozenset().union(*(t.requires for t in reflex.TOOLS))  # a desktop that can do it all


def _found(texts: str | list[str] | None) -> list[Found]:
    items = [texts] if isinstance(texts, str) else texts or []
    return [Found(uuid.uuid4(), "fact", t) for t in items]


def turn_prompt(row: dict[str, Any]) -> tuple[str, str]:
    """(system, user message) exactly as the reflex builds them, with the row's memories."""
    ctx = Context(None, [], "Laptop", profile=_found(row.get("profile")))
    note = reflex.volatile_context(ctx, 345, NOW, remembered=_found(row.get("remembered")))
    return reflex.system(ctx), f"{row['text']}\n\n{note}"


@dataclass
class EntryResult:
    label: str
    ttft_ms: list[float] = field(default_factory=list)
    passed: dict[str, int] = field(default_factory=dict)
    total: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    banned: int = 0
    failures: list[str] = field(default_factory=list)

    def pct(self, q: float) -> float | None:
        if not self.ttft_ms:
            return None
        ordered = sorted(self.ttft_ms)
        return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def args_match(want: dict[str, Any], got: dict[str, Any]) -> bool:
    for key, value in want.items():
        have = got.get(key)
        if isinstance(value, str):
            if not isinstance(have, str) or value.lower() not in have.lower():
                return False
        elif have != value:
            return False
    return True


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_UNSPEAKABLE = re.compile(r"[*#`]|^\s*(?:[-•]|\d+\.)\s|https?://|[\U0001F300-\U0001FAFF]", re.M)


def persona_misses(text: str) -> list[str]:
    """PERSONA.md §2 spoken-style rules a reply breaks (empty list = passes)."""
    _, body = persona.split_tone(text.strip())
    sentences = [s for s in _SENTENCE_END.split(body) if s.strip()]
    misses = []
    if not sentences:
        misses.append("silent")
    if len(sentences) > 3:
        misses.append(f"{len(sentences)} sentences")
    if any(len(s.split()) > 25 for s in sentences):
        misses.append("long sentence")
    if persona.has_banned(body):
        misses.append("banned phrase")
    if _UNSPEAKABLE.search(body):
        misses.append("markdown/list/link/emoji")
    return misses


def grade(row: dict[str, Any], text: str, uses: list[ToolUse]) -> bool:
    names = [u.name for u in uses]
    low = text.lower()
    if any(w.lower() in low for w in row.get("not_words", [])):
        return False  # e.g. a sister's name nobody told it
    if row["expect"] == "persona":  # graded as spoken: the speech lint strips emoji and markdown
        return not uses and not persona_misses(persona.lint(text))
    if row["expect"] == "answer":
        return bool(text.strip()) and not uses
    if row["expect"] == "mentions":  # used what it remembers, in words, without delegating
        return "delegate" not in names and any(w.lower() in low for w in row["words"])
    if row["expect"] == "delegate":
        return "delegate" in names
    return any(u.name == row["tool"] and args_match(row["args"], u.input) for u in uses)


def _has(text: str, word: str) -> bool:
    """`word` may list alternatives: "short|brief|concise"."""
    return any(w.lower() in text.lower() for w in word.split("|"))


def grade_memory(row: dict[str, Any], items: list[extract.Item]) -> bool:
    """Every expected memory found (its words, its kind if given), at most one extra, and the
    right `replaces` for corrections. Expecting nothing means nothing."""
    want: list[dict[str, Any]] = row["expect"]
    if not want:
        return not items
    if len(items) > len(want) + 1:
        return False
    for w in want:
        if not any(
            all(_has(i.text, x) for x in w["words"]) and w.get("kind", i.kind) == i.kind
            for i in items
        ):
            return False
    return "replaces" not in row or any(i.replaces == row["replaces"] for i in items)


async def run_memory_entry(
    http: httpx.AsyncClient,
    label: str,
    base_url: str,
    keys: list[str],
    model: str,
    extra: dict[str, Any],
    rows: list[dict[str, Any]],
    spacing_s: float,
) -> EntryResult:
    res = EntryResult(label)
    turn = 0
    for row in rows:
        kind = "learn" if row["expect"] else "skip"
        res.total[kind] = res.total.get(kind, 0) + 1
        text = ""
        if extract.personal(row["said"]):  # otherwise the brain never calls the model
            asked = extract.prompt(row.get("known", []), row["said"], row.get("reply", "Okay."))
            messages = [{"role": "user", "content": [{"type": "text", "text": asked}]}]
            error: ProviderError | None = None
            for _ in keys:
                turn += 1
                t0 = time.perf_counter()
                try:
                    async for ev in openai_compat.stream(
                        http,
                        base_url=base_url,
                        api_key=keys[turn % len(keys)],
                        model=model,
                        system=extract.SYSTEM,
                        messages=messages,
                        max_tokens=600,
                        extra=extra,
                    ):
                        if isinstance(ev, TextDelta):
                            text += ev.text
                    res.ttft_ms.append((time.perf_counter() - t0) * 1000)  # whole call here
                    error = None
                    break
                except ProviderError as exc:
                    error = exc
                    if exc.kind != "rate_limited":
                        break
            if error is not None:
                res.errors += 1
                res.failures.append(f"{row['said']!r}: {error.kind}")
                await asyncio.sleep(spacing_s)
                continue
            await asyncio.sleep(spacing_s)
        items = extract.parse(text)
        if grade_memory(row, items):
            res.passed[kind] = res.passed.get(kind, 0) + 1
        else:
            got = "; ".join(f"{i.kind}: {i.text} (r={i.replaces})" for i in items) or "nothing"
            res.failures.append(f"{row['said']!r} → {got}")
    return res


def report_memory(results: list[EntryResult]) -> None:
    print("\n| entry | call p50 | learned | skipped | errors |")
    print("|---|---|---|---|---|")
    for r in results:
        cells = [f"{r.passed.get(k, 0)}/{r.total.get(k, 0)}" for k in ("learn", "skip")]
        print(f"| {r.label} | {r.pct(0.5) or 0:.0f} ms | {' | '.join(cells)} | {r.errors} |")
    for r in results:
        if r.failures:
            print(f"\n{r.label} misses ({len(r.failures)}):")
            for f in r.failures[:15]:
                print(f"  - {f}")


async def run_entry(
    http: httpx.AsyncClient,
    label: str,
    base_url: str,
    keys: list[str],
    model: str,
    extra: dict[str, Any],
    rows: list[dict[str, Any]],
    spacing_s: float,
) -> EntryResult:
    res = EntryResult(label)
    turn = 0  # round-robin over the keys, like the chain runner; free TPM limits are small
    for row in rows:
        kind = row["expect"]
        res.total[kind] = res.total.get(kind, 0) + 1
        system, said = turn_prompt(row)
        messages = [{"role": "user", "content": [{"type": "text", "text": said}]}]
        error: ProviderError | None = None
        for _ in keys:
            turn += 1
            t0 = time.perf_counter()
            first: float | None = None
            text, uses = "", []
            try:
                async for ev in openai_compat.stream(
                    http,
                    base_url=base_url,
                    api_key=keys[turn % len(keys)],
                    model=model,
                    system=system,
                    messages=messages,
                    tools=reflex.tool_defs(ALL_CAPS, said=row["text"]),
                    max_tokens=300,
                    extra=extra,
                ):
                    if first is None and isinstance(ev, TextDelta | ToolUse):
                        first = (time.perf_counter() - t0) * 1000
                    if isinstance(ev, TextDelta):
                        text += ev.text
                    elif isinstance(ev, ToolUse):
                        uses.append(ev)
                error = None
                break
            except ProviderError as exc:
                error = exc
                if exc.kind != "rate_limited":
                    break
        if error is not None:
            res.errors += 1
            res.failures.append(f"{row['text']!r}: {error.kind}")
            await asyncio.sleep(spacing_s)
            continue
        if first is not None:
            res.ttft_ms.append(first)
        if persona.has_banned(text):
            res.banned += 1
        if grade(row, text, uses):
            res.passed[kind] = res.passed.get(kind, 0) + 1
        else:
            got = ", ".join(f"{u.name}{json.dumps(u.input)}" for u in uses) or text[:80]
            res.failures.append(f"{row['text']!r} → {got}")
        await asyncio.sleep(spacing_s)
    return res


def report(results: list[EntryResult]) -> None:
    kinds = ("answer", "tool", "delegate", "persona", "mentions")
    print("\n| entry | TTFT p50 | p95 | reflex-grade | answers | tools | delegate | persona "
          "| memory | errors | banned |")  # fmt: skip
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        p50, p95 = r.pct(0.5), r.pct(0.95)
        grade_ok = p95 is not None and p95 <= TTFT_GATE_MS
        cells = [f"{r.passed.get(k, 0)}/{r.total.get(k, 0)}" for k in kinds]
        print(
            f"| {r.label} | {p50 or 0:.0f} ms | {p95 or 0:.0f} ms | {'yes' if grade_ok else 'no'} "
            f"| {' | '.join(cells)} | {r.errors} | {r.banned} |"
        )
    for r in results:
        if r.failures:
            print(f"\n{r.label} misses ({len(r.failures)}):")
            for f in r.failures[:15]:
                print(f"  - {f}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["reflex", "persona", "memory"], default="reflex")
    ap.add_argument("--entry", help="only this provider/model, e.g. groq/openai/gpt-oss-20b")
    ap.add_argument("--limit", type=int, default=0, help="first N rows only")
    ap.add_argument("--expect", nargs="*", help="only rows expecting these (tool, delegate, …)")
    ap.add_argument(
        "--spacing", type=float, default=2.0, help="seconds between calls (keys rotate)"
    )
    ap.add_argument("--allow-training", action="store_true", help="include Gemini (trains on data)")
    args = ap.parse_args()

    settings = Settings()
    rows = [
        json.loads(line)
        for line in (EVALS / f"{args.suite}.jsonl").read_text().splitlines()
        if line
    ]
    if args.expect:
        rows = [r for r in rows if r.get("expect") in args.expect]
    if args.limit:
        rows = rows[: args.limit]
    table = providers(settings)
    results = []
    async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(20, connect=5)) as http:
        for entry in CHAINS["memory" if args.suite == "memory" else "reflex"]:
            label = f"{entry.provider}/{entry.model}"
            if args.entry and label != args.entry:
                continue
            if entry.paid and not settings.paid_providers_enabled:
                continue
            if entry.trains_on_data and not args.allow_training:
                continue
            base_url, keys = table.get(entry.provider, ("", []))
            if not keys:
                print(f"skip {label}: no key")
                continue
            print(f"running {label} on {len(rows)} utterances, {len(keys)} key(s)…", flush=True)
            run = run_memory_entry if args.suite == "memory" else run_entry
            results.append(
                await run(http, label, base_url, keys, entry.model, entry.extra, rows, args.spacing)
            )
    if not results:
        print("No entries ran. Add GROQ_API_KEYS (and others) to deploy/.env.")
        return
    if args.suite == "memory":
        report_memory(results)
        return
    report(results)
    ttfts = [t for r in results for t in r.ttft_ms]
    if ttfts:
        print(
            f"\nall entries: median TTFT {statistics.median(ttfts):.0f} ms over {len(ttfts)} calls"
        )


if __name__ == "__main__":
    asyncio.run(main())
