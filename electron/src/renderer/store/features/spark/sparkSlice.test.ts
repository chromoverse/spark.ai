import { describe, expect, it } from "vitest";
import type { IBrainEvent } from "@root/types";
import reducer, { brainEvent, currentJob, initialSparkState, userSaid, type SparkState, type Turn } from "./sparkSlice";

const ev = (event: string, data: Record<string, unknown>) => brainEvent({ event, data } as IBrainEvent);
const run = (...actions: Parameters<typeof reducer>[1][]): SparkState => actions.reduce(reducer, initialSparkState);
const turns = (s: SparkState) => s.entries.filter((e): e is Turn => e.kind === "turn");

describe("sparkSlice", () => {
  it("folds Spark's sentences into the turn the user started, then ends it", () => {
    const s = run(
      userSaid({ signalId: "s1", text: "what's on my desktop", tier: 2 }),
      ev("reply.delta", { signal_id: "s1", text: "Three files.", speak: true, final: false }),
      ev("reply.delta", { signal_id: "s1", text: "Want the list?", speak: true, final: false }),
      ev("reply.delta", { signal_id: "s1", text: "", speak: false, final: true }),
    );
    expect(turns(s)).toHaveLength(1);
    expect(turns(s)[0]).toMatchObject({ you: "what's on my desktop", spark: "Three files. Want the list?", done: true });
    expect(turns(s)[0].at).toBeGreaterThan(0);
  });

  it("a speculative reply that replays before the line is confirmed stays one turn", () => {
    const s = run(
      ev("reply.delta", { signal_id: "s1", text: "It's 3 pm.", speak: true, final: false }),
      userSaid({ signalId: "s1", text: "what time is it", tier: 2 }),
      ev("reply.delta", { signal_id: "s1", text: "", speak: false, final: true }),
    );
    expect(turns(s)).toHaveLength(1);
    expect(turns(s)[0]).toMatchObject({ you: "what time is it", spark: "It's 3 pm.", done: true });
  });

  it("a job speaking after its turn ended is a new Spark line", () => {
    const s = run(
      userSaid({ signalId: "s1", text: "tidy my downloads", tier: 3 }),
      ev("reply.delta", { signal_id: "s1", text: "On it.", speak: true, final: true }),
      ev("reply.delta", { signal_id: "s1", text: "Done: 12 files sorted.", speak: true, final: true }),
    );
    expect(turns(s).map((t) => [t.you, t.spark])).toEqual([
      ["tidy my downloads", "On it."],
      [null, "Done: 12 files sorted."],
    ]);
  });

  it("an approval card closes when any device answers, and when its job ends", () => {
    const request = (id: string) =>
      ev("approval.request", { approval_id: id, job_id: "j1", tool: "file_delete", summary: "Delete a.txt", inputs_preview: {}, risk: "destructive", options: ["allow", "deny"] });
    let s = run(request("a1"), request("a2"));
    expect(s.approvals.map((a) => a.id)).toEqual(["a1", "a2"]);
    s = reducer(s, ev("approval.resolved", { approval_id: "a1", decision: "allow" }));
    expect(s.approvals.map((a) => a.id)).toEqual(["a2"]);
    s = reducer(s, ev("job.update", { job_id: "j1", status: "cancelled", title: "Clean up", todo: [] }));
    expect(s.approvals).toEqual([]);
  });

  it("the current job is the newest active one", () => {
    const s = run(
      ev("job.update", { job_id: "j1", status: "running", title: "One", todo: [] }),
      ev("job.update", { job_id: "j2", status: "done", title: "Two", todo: [] }),
    );
    expect(currentJob(s)?.id).toBe("j1");
  });
});
