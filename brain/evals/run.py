"""Live reflex eval (TESTING.md §7, REDESIGN §5.5): runs every reflex chain entry that has a key
against `evals/reflex.jsonl` and reports time to first token, tool-call validity, answers, and
banned phrases. The p95 TTFT gate (400 ms) decides which entries are reflex-grade.

    cd brain && uv run python -m evals.run --suite reflex [--limit 20]
        [--entry groq/openai/gpt-oss-20b]

Never in PR CI: it calls free providers and spends their daily quota (Groq: 1K requests/day).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.agent import persona, reflex
from app.core.config import Settings
from app.llm import openai_compat
from app.llm.chains import CHAINS, providers
from app.llm.types import ProviderError, TextDelta, ToolUse

EVALS = Path(__file__).resolve().parent
TTFT_GATE_MS = 400.0
CONTEXT = "(context: it's Saturday 10 October 2026, 2:05 PM local time; device: Laptop)"


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


def grade(row: dict[str, Any], text: str, uses: list[ToolUse]) -> bool:
    names = [u.name for u in uses]
    if row["expect"] == "answer":
        return bool(text.strip()) and not uses
    if row["expect"] == "delegate":
        return "delegate" in names
    return any(u.name == row["tool"] and args_match(row["args"], u.input) for u in uses)


async def run_entry(
    http: httpx.AsyncClient,
    label: str,
    base_url: str,
    api_key: str,
    model: str,
    extra: dict[str, Any],
    rows: list[dict[str, Any]],
    spacing_s: float,
) -> EntryResult:
    res = EntryResult(label)
    for row in rows:
        kind = row["expect"]
        res.total[kind] = res.total.get(kind, 0) + 1
        messages = [
            {"role": "user", "content": [{"type": "text", "text": f"{row['text']}\n\n{CONTEXT}"}]}
        ]
        t0 = time.perf_counter()
        first: float | None = None
        text, uses = "", []
        try:
            async for ev in openai_compat.stream(
                http,
                base_url=base_url,
                api_key=api_key,
                model=model,
                system=reflex.SYSTEM,
                messages=messages,
                tools=reflex.TOOL_DEFS,
                max_tokens=300,
                extra=extra,
            ):
                if first is None and isinstance(ev, TextDelta | ToolUse):
                    first = (time.perf_counter() - t0) * 1000
                if isinstance(ev, TextDelta):
                    text += ev.text
                elif isinstance(ev, ToolUse):
                    uses.append(ev)
        except ProviderError as exc:
            res.errors += 1
            res.failures.append(f"{row['text']!r}: {exc.kind}")
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
    print(
        "\n| entry | TTFT p50 | p95 | reflex-grade | answers | tools | delegate | errors | banned |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        p50, p95 = r.pct(0.5), r.pct(0.95)
        grade_ok = p95 is not None and p95 <= TTFT_GATE_MS
        cells = [
            f"{r.passed.get(k, 0)}/{r.total.get(k, 0)}" for k in ("answer", "tool", "delegate")
        ]
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
    ap.add_argument("--suite", choices=["reflex"], default="reflex")
    ap.add_argument("--entry", help="only this provider/model, e.g. groq/openai/gpt-oss-20b")
    ap.add_argument("--limit", type=int, default=0, help="first N rows only")
    ap.add_argument(
        "--spacing", type=float, default=2.1, help="seconds between calls (Groq: 30 RPM)"
    )
    ap.add_argument("--allow-training", action="store_true", help="include Gemini (trains on data)")
    args = ap.parse_args()

    settings = Settings()
    rows = [json.loads(line) for line in (EVALS / "reflex.jsonl").read_text().splitlines() if line]
    if args.limit:
        rows = rows[: args.limit]
    table = providers(settings)
    results = []
    async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(20, connect=5)) as http:
        for entry in CHAINS["reflex"]:
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
            print(f"running {label} on {len(rows)} utterances…")
            results.append(
                await run_entry(
                    http, label, base_url, keys[0], entry.model, entry.extra, rows, args.spacing
                )
            )
    if not results:
        print("No entries ran. Add GROQ_API_KEYS (and others) to deploy/.env.")
        return
    report(results)
    ttfts = [t for r in results for t in r.ttft_ms]
    if ttfts:
        print(
            f"\nall entries: median TTFT {statistics.median(ttfts):.0f} ms over {len(ttfts)} calls"
        )


if __name__ == "__main__":
    asyncio.run(main())
