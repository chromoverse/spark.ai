import { useEffect, useState } from "react";
import { Gauge, RefreshCw } from "lucide-react";
import type { IBodyStatus, IEnginesInfo } from "@root/types";
import { useBrainGet } from "@/hooks/useBrainGet";
import { Dot, ListState, Page, Tabs } from "./ui";

// Engines (DESIGN.md §3): how Spark runs on this device. Voice = this device's measured voice
// engines and the benchmark; Models = each role's chain, free first, with health and speed.

const TABS = [
  { id: "voice", label: "Voice" },
  { id: "models", label: "Models" },
] as const;

const BODY_COPY: Record<IBodyStatus, string> = {
  ready: "Voice engine running.",
  starting: "Starting the voice engine…",
  down: "The voice engine stopped. Restarting it…",
  missing: "The voice engine isn't installed yet. Run `uv sync` in body/.",
};

const ms = (v: number | null | undefined): string => (v == null ? "—" : `${Math.round(v)} ms`);

export default function EnginesHub() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("voice");
  const [info, setInfo] = useState<IEnginesInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);

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
    return () => {
      offPlan();
      offStatus();
    };
  }, []);

  const benchmark = async (): Promise<void> => {
    setBenchmarking(true);
    const r = await window.electronApi.engines.runBenchmark();
    setBenchmarking(false);
    if (r.ok) setInfo(r.data);
    else setError(r.error.message);
  };

  return (
    <Page
      title="Engines"
      tabs={<Tabs value={tab} options={TABS} onChange={setTab} />}
      actions={
        tab === "voice" && (
          <button className="sp-btn-ghost px-3" onClick={() => void benchmark()} disabled={benchmarking || info?.bodyStatus !== "ready"}>
            {benchmarking ? <RefreshCw className="size-3.5 animate-spin" /> : <Gauge className="size-3.5" />}
            {benchmarking ? "Benchmarking…" : "Run benchmark"}
          </button>
        )
      }
    >
      {tab === "voice" ? <Voice info={info} error={error} /> : <Models />}
    </Page>
  );
}

function Voice({ info, error }: { info: IEnginesInfo | null; error: string | null }) {
  const plan = info?.plan;
  const scores = plan ? Object.values(plan.scores) : [];
  const downloads = Object.entries(plan?.models ?? {}).filter(([, m]) => m.state !== "ready");
  return (
    <div className="flex flex-col gap-3 px-6 py-5">
      {error && (
        <p role="alert" className="text-[13px] text-[var(--sp-err)]">
          {error}
        </p>
      )}
      <p className="text-[13px] text-[var(--sp-ink-2)]">{info ? BODY_COPY[info.bodyStatus] : "Checking the voice engine…"}</p>
      {info?.bodyStatus === "ready" && scores.length === 0 && (
        <p className="text-[13px] text-[var(--sp-ink-3)]">No engines measured yet. Run a benchmark to pick the fastest voice.</p>
      )}
      {scores.length > 0 && (
        <div className="sp-box px-2 py-1">
          <table className="sp-table">
            <thead>
              <tr>
                <th>Engine</th>
                <th>In use</th>
                <th>p50</th>
                <th>p95</th>
                <th>Live avg</th>
                <th>Success</th>
              </tr>
            </thead>
            <tbody>
              {scores.map((s) => {
                const rank = (s.role === "stt" ? plan?.stt : plan?.tts)?.indexOf(s.engine) ?? -1;
                return (
                  <tr key={s.engine}>
                    <td>
                      <span className="text-[var(--sp-ink)]">{s.engine}</span>
                      <span className="ml-1.5 text-[12px] text-[var(--sp-ink-4)]">
                        {s.role === "stt" ? "speech to text" : "voice"}
                        {s.expressive && ", expressive"}
                        {s.accuracy != null && `, ${Math.round(s.accuracy * 100)}% words right`}
                      </span>
                      {plan?.reasons?.[s.engine] && <div className="text-[12px] text-[var(--sp-warn)]">{plan.reasons[s.engine]}</div>}
                    </td>
                    <td className={rank >= 0 ? "text-[var(--sp-ink)]" : "text-[var(--sp-ink-4)]"}>{rank >= 0 ? `#${rank + 1}` : "off"}</td>
                    <td className="sp-mono text-[12px]">{ms(s.p50_ms)}</td>
                    <td className="sp-mono text-[12px]">{ms(s.p95_ms)}</td>
                    <td className="sp-mono text-[12px]">{ms(s.ewma_ms)}</td>
                    <td className="sp-mono text-[12px]">{Math.round(s.success * 100)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {plan && plan.tts.length === 0 && scores.length > 0 && (
        <p className="text-[13px] text-[var(--sp-ink-3)]">No voice passed on this device, so replies show as text.</p>
      )}
      {downloads.map(([name, m]) => (
        <p key={name} className={`text-[13px] ${m.state === "failed" ? "text-[var(--sp-warn)]" : "text-[var(--sp-ink-3)]"}`}>
          {m.state === "failed" ? `Couldn't download ${name}. I'll try again next time the app starts.` : `Downloading ${name} for this device (${m.mb} MB)… ${m.pct}%`}
        </p>
      ))}
      {plan?.wake && <p className="text-[13px] text-[var(--sp-ink-3)]">Wake word ready: say “Hey Spark” with the mic on.</p>}
    </div>
  );
}

interface ChainEntry {
  provider: string;
  model: string;
  paid: boolean;
  trains_on_data: boolean;
  keys: number;
  enabled: boolean;
  healthy: boolean;
  ttft_ms: number | null;
}

const ROLE_COPY: Record<string, string> = {
  reflex: "Quick replies",
  agent: "Jobs (agent)",
  subagent: "Sub-tasks",
  review: "Safety check",
};

function Models() {
  const chains = useBrainGet<{ roles: Record<string, ChainEntry[]> }>("/v2/engines/chains");
  const roles = Object.entries(chains.data?.roles ?? {});
  return (
    <ListState loading={chains.loading} error={chains.error} empty={roles.length === 0 && "No model chains configured."}>
      <div className="grid grid-cols-1 gap-4 px-6 py-5 xl:grid-cols-2">
        {roles.map(([role, entries]) => (
          <section key={role} className="sp-box px-4 py-3">
            <h4 className="mb-2 flex items-baseline gap-2 text-[13px] font-medium text-[var(--sp-ink)]">
              {ROLE_COPY[role] ?? role}
              <span className="sp-mono text-[11px] font-normal text-[var(--sp-ink-4)]">{role} · free first</span>
            </h4>
            <table className="sp-table">
              <tbody>
                {entries.map((e, i) => (
                  <tr key={`${e.provider}/${e.model}`}>
                    <td className="w-6 text-[var(--sp-ink-4)]">{e.enabled ? i + 1 : "·"}</td>
                    <td>
                      <span className="text-[var(--sp-ink)]">{e.model}</span>
                      <span className="ml-1.5 text-[12px] text-[var(--sp-ink-4)]">{e.provider}</span>
                    </td>
                    <td>
                      <span className="inline-flex items-center gap-1.5 text-[12px]">
                        <Dot tone={!e.enabled ? "off" : e.healthy ? "ok" : "warn"} />
                        {e.paid && !e.enabled ? "paid, off" : !e.keys ? "no key" : !e.enabled ? "off" : e.healthy ? "healthy" : "cooling down"}
                      </span>
                    </td>
                    <td className="sp-mono text-right text-[12px]">{e.ttft_ms != null ? `${e.ttft_ms} ms` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>
    </ListState>
  );
}
