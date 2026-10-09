import { Cpu, Gauge, Play, RefreshCw, Send, Square } from "lucide-react";
import { useEffect, useState } from "react";
import type { IBodyStatus, IBrainEvent, IEnginesInfo } from "@root/types";

// Engines (docs/REDESIGN.md §24): this device's voice engines with their measured scores, why an
// engine was switched off, and a "Run benchmark" button. "Try it" sends a line through the whole
// R1 loop (tier 0 on the device, then the brain) and shows the reply as it streams in.

const BODY_COPY: Record<IBodyStatus, string> = {
  ready: "Voice engine running.",
  starting: "Starting the voice engine…",
  down: "The voice engine stopped. Restarting it…",
  missing: "The voice engine isn't installed yet. Run `uv sync` in body/.",
};

function ms(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value)} ms`;
}

interface Turn {
  signalId: string;
  you: string;
  spark: string;
  tier: number | null;
  done: boolean;
}

export default function EnginesPage() {
  const [info, setInfo] = useState<IEnginesInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);

  useEffect(() => {
    const load = (): void => {
      void window.electronApi.engines.get().then((r) => {
        if (r.ok) {
          setInfo(r.data);
          setError(null);
        } else setError(r.error.message);
      });
    };
    load();
    const offPlan = window.electronApi.engines.onPlan(load);
    const offStatus = window.electronApi.engines.onBodyStatus(load);
    const offEvent = window.electronApi.brain.onEvent(({ event, data }: IBrainEvent) => {
      if (event !== "reply.delta") return;
      const d = data as { signal_id: string; text: string; final: boolean };
      setTurns((all) =>
        all.map((t) =>
          t.signalId === d.signal_id
            ? { ...t, spark: d.text ? `${t.spark} ${d.text}`.trim() : t.spark, done: t.done || d.final }
            : t,
        ),
      );
    });
    return () => {
      offPlan();
      offStatus();
      offEvent();
    };
  }, []);

  const benchmark = async () => {
    setBenchmarking(true);
    const r = await window.electronApi.engines.runBenchmark();
    setBenchmarking(false);
    if (r.ok) setInfo(r.data);
    else setError(r.error.message);
  };

  const send = async () => {
    const line = text.trim();
    if (!line) return;
    setText("");
    const r = await window.electronApi.voice.send(line);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    const { signalId, tier, handled, error: why } = r.data;
    setTurns((all) => [
      ...all.slice(-9),
      { signalId, you: line, tier, spark: why ?? (handled ? "(handled on this device)" : ""), done: handled || !!why },
    ]);
  };

  const plan = info?.plan;
  const scores = plan ? Object.values(plan.scores) : [];

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6" style={{ color: "var(--sp-ink)" }}>
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu size={18} />
          <h1 className="text-lg font-semibold">Engines</h1>
        </div>
        <button
          type="button"
          onClick={() => void benchmark()}
          disabled={benchmarking || info?.bodyStatus !== "ready"}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          {benchmarking ? <RefreshCw size={14} className="animate-spin" /> : <Gauge size={14} />}
          {benchmarking ? "Benchmarking…" : "Run benchmark"}
        </button>
      </header>

      {error && (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium opacity-70">Voice on this device</h2>
        {!info ? (
          <p className="text-sm opacity-60">Checking the voice engine…</p>
        ) : (
          <p className="text-sm">{BODY_COPY[info.bodyStatus]}</p>
        )}
        {info?.bodyStatus === "ready" && scores.length === 0 && (
          <p className="text-sm opacity-60">No engines measured yet. Run a benchmark to pick the fastest voice.</p>
        )}
        {scores.length > 0 && (
          <table className="w-full text-sm">
            <thead className="opacity-60 text-left">
              <tr>
                <th className="py-1">Engine</th>
                <th>In use</th>
                <th>First audio p50</th>
                <th>p95</th>
                <th>Live avg</th>
                <th>Success</th>
              </tr>
            </thead>
            <tbody>
              {scores.map((s) => {
                const rank = plan?.tts.indexOf(s.engine) ?? -1;
                return (
                  <tr key={s.engine} className="border-t border-white/10">
                    <td className="py-1.5">
                      {s.engine}
                      {s.expressive && <span className="ml-1 text-xs opacity-60">(expressive)</span>}
                      {plan?.reasons?.[s.engine] && (
                        <div className="text-xs text-amber-500">{plan.reasons[s.engine]}</div>
                      )}
                    </td>
                    <td>{rank >= 0 ? `#${rank + 1}` : "off"}</td>
                    <td>{ms(s.p50_ms)}</td>
                    <td>{ms(s.p95_ms)}</td>
                    <td>{ms(s.ewma_ms)}</td>
                    <td>{Math.round(s.success * 100)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {plan && plan.tts.length === 0 && scores.length > 0 && (
          <p className="text-sm opacity-60">No voice passed on this device, so replies show as text.</p>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium opacity-70">Try it</h2>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Say something, like “what time is it” or “tell me a joke”"
            aria-label="Message to Spark"
            className="flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm"
          />
          <button type="submit" className="inline-flex items-center gap-1 rounded-md border px-3 text-sm" aria-label="Send">
            <Send size={14} />
          </button>
          <button
            type="button"
            onClick={() => void window.electronApi.voice.stop()}
            className="inline-flex items-center gap-1 rounded-md border px-3 text-sm"
            aria-label="Stop speaking"
          >
            <Square size={14} />
          </button>
        </form>
        {turns.length === 0 ? (
          <p className="text-sm opacity-60">Nothing yet. Simple things run right here; the rest goes to the brain.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {turns.map((t) => (
              <li key={t.signalId}>
                <div className="opacity-70">you: {t.you}</div>
                <div className="flex items-start gap-1.5">
                  <Play size={12} className="mt-1 shrink-0 opacity-50" />
                  <span>
                    {t.spark || (t.done ? "" : "…")}
                    {t.tier != null && <span className="ml-1 text-xs opacity-50">tier {t.tier}</span>}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
