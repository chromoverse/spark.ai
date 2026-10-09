"""Latency report from the brain's JSON logs (TESTING.md §6): device-measured end of speech →
first audio, plus the brain's own spans. Gate: p50 < 1000 ms, p95 < 1500 ms.

    uv run python -m evals.latency < brain.log
    (docker: `docker compose -f deploy/docker-compose.yml logs brain --no-log-prefix > brain.log`)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Iterable

GATE_P50_MS, GATE_P95_MS = 1000.0, 1500.0


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def collect(lines: Iterable[str]) -> dict[str, list[float]]:
    spans: dict[str, list[float]] = defaultdict(list)
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("msg") == "signal trace":
            for name, ms in (rec.get("device_spans") or {}).items():
                spans[f"device.{name}"].append(float(ms))
        elif rec.get("msg") == "signal done" and rec.get("tier") == 2:
            for name, ms in (rec.get("spans") or {}).items():
                if not name.startswith("tool"):
                    spans[f"brain.{name}"].append(float(ms))
    return spans


def main() -> int:
    spans = collect(sys.stdin)
    if not spans:
        print("No signal traces in the input.")
        return 1
    print("| span | n | p50 | p95 |")
    print("|---|---|---|---|")
    for name in sorted(spans):
        v = spans[name]
        print(f"| {name} | {len(v)} | {pct(v, 0.5):.0f} ms | {pct(v, 0.95):.0f} ms |")
    first = spans.get("device.first_audio")
    if not first:
        print("\nNo device first_audio spans yet (talk to Spark from the desktop app).")
        return 1
    p50, p95 = pct(first, 0.5), pct(first, 0.95)
    ok = p50 < GATE_P50_MS and p95 < GATE_P95_MS
    verdict = "PASS" if ok else "FAIL"
    print(f"\nend of speech → first audio: p50 {p50:.0f} ms, p95 {p95:.0f} ms → {verdict}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
