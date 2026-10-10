import { describe, expect, it } from "vitest";
import type { JobView, Turn } from "@/store/features/spark/sparkSlice";
import { LINGER_MS, lingering, overlayLayout, overlayMode, type OverlayInputs } from "./overlayMode";

const NOW = 1_000_000;
const turn = (patch: Partial<Turn> = {}): Turn => ({ kind: "turn", key: "e1", signalId: "s1", you: "hi", spark: "", done: false, tier: 2, at: NOW, ...patch });
const job = { id: "j1", title: "Tidy downloads", status: "running", todo: [], etaS: null, steps: [], note: null, summary: null, artifactId: null } as JobView;
const base: OverlayInputs = { now: NOW, armed: false, speaking: false, turn: null, turnAt: 0, waiting: 0, job: null };

describe("overlay mode", () => {
  it("rests as a small notch when nothing is going on", () => {
    expect(overlayMode(base)).toBe("idle");
    expect(overlayLayout("idle", false, false)).toBe("compact");
  });

  it("opens for a bare Hey Spark, a pending reply, and Spark's voice", () => {
    expect(overlayMode({ ...base, armed: true })).toBe("listening");
    expect(overlayMode({ ...base, turn: turn(), turnAt: NOW })).toBe("thinking");
    expect(overlayMode({ ...base, speaking: true, turn: turn({ spark: "Hi." }), turnAt: NOW })).toBe("speaking");
    for (const m of ["listening", "thinking", "speaking"] as const) expect(overlayLayout(m, false, false)).toBe("full");
  });

  it("an approval or a question outranks everything", () => {
    expect(overlayMode({ ...base, speaking: true, armed: true, job, waiting: 1 })).toBe("attention");
    expect(overlayLayout("attention", false, false)).toBe("full");
  });

  it("a running job shows small, and full on hover", () => {
    expect(overlayMode({ ...base, job })).toBe("working");
    expect(overlayLayout("working", false, false)).toBe("live");
    expect(overlayLayout("working", true, false)).toBe("full");
  });

  it("a turn the brain never finished stops thinking", () => {
    expect(overlayMode({ ...base, turn: turn(), turnAt: NOW - 31_000 })).toBe("idle");
  });

  it("a finished exchange stays readable, then the notch closes", () => {
    const t = turn({ spark: "Done.", done: true });
    expect(lingering({ now: NOW, turn: t, turnAt: NOW - 1_000 })).toBe(true);
    expect(lingering({ now: NOW, turn: t, turnAt: NOW - LINGER_MS })).toBe(false);
    expect(overlayLayout("idle", false, true)).toBe("full");
  });
});
