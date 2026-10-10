import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { IBrainJob } from "@root/types";
import { useAppSelector } from "@/store/hooks";
import { useBrainGet } from "@/hooks/useBrainGet";
import { ago } from "./logic";
import { ListState, Page, Tabs, Tag } from "./ui";

// Activity (DESIGN.md §3): what happened. Jobs with their step log, and the supervisor's incidents.

interface Step {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  output: string | null;
  status: string;
  error: string | null;
  started_at: string | null;
}
interface Incident {
  id: string;
  stage: string;
  engine_or_provider: string | null;
  error: string;
  remedy: string | null;
  outcome: string | null;
  ts: string;
}

const TABS = [
  { id: "jobs", label: "Jobs" },
  { id: "incidents", label: "Incidents" },
] as const;

export default function ActivityPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("jobs");
  return (
    <Page title="Activity" tabs={<Tabs value={tab} options={TABS} onChange={setTab} />}>
      {tab === "jobs" ? <Jobs /> : <Incidents />}
    </Page>
  );
}

function Jobs() {
  const jobs = useBrainGet<{ items: (IBrainJob & { created_at: string })[] }>("/v2/jobs?limit=50");
  const [open, setOpen] = useState<string | null>(null);
  // a job changed somewhere (job.update): refresh the list
  const live = useAppSelector((s) => s.spark.jobOrder.map((id) => `${id}:${s.spark.jobs[id].status}`).join());
  const { reload } = jobs;
  useEffect(() => {
    reload();
  }, [live, reload]);

  const items = jobs.data?.items ?? [];
  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 px-6 py-4">
        <ListState loading={jobs.loading && !jobs.data} error={jobs.error} empty={items.length === 0 && "No jobs yet. Ask for something with a few steps, like “tidy my downloads”."}>
          <table className="sp-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Status</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id} onClick={() => setOpen(j.id)} className="cursor-pointer">
                  <td className="text-[var(--sp-ink)]">
                    {j.title}
                    {j.summary && <div className="mt-0.5 truncate text-[12px] text-[var(--sp-ink-4)]">{j.summary}</div>}
                  </td>
                  <td>
                    <Tag kind={j.status} />
                  </td>
                  <td className="whitespace-nowrap text-[12px] text-[var(--sp-ink-4)]">{ago(j.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ListState>
      </div>
      {open && <JobDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function JobDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const job = useBrainGet<IBrainJob & { steps: Step[] }>(`/v2/jobs/${id}`);
  return (
    <aside className="sp-scroll flex w-[380px] shrink-0 flex-col overflow-y-auto border-l border-[var(--sp-line)] bg-[var(--sp-bg-2)]">
      <header className="flex items-center gap-2 border-b border-[var(--sp-line)] px-4 py-3">
        <h3 className="truncate text-[13.5px] font-medium text-[var(--sp-ink)]">{job.data?.title ?? "Job"}</h3>
        <button className="sp-btn-ghost ml-auto size-7 min-w-7" onClick={onClose} aria-label="Close">
          <X className="size-3.5" />
        </button>
      </header>
      <ListState loading={job.loading} error={job.error} empty={job.data?.steps.length === 0 && "No steps ran."}>
        <ol className="flex flex-col gap-3 px-4 py-3">
          {job.data?.steps.map((s) => (
            <li key={s.id} className="rounded-lg bg-white/[0.03] px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="sp-mono text-[12px] text-[var(--sp-ink)]">{s.tool}</span>
                <span className={`sp-tag ml-auto sp-tag-${s.status === "ok" ? "done" : s.status === "error" ? "failed" : s.status === "denied" ? "cancelled" : "running"}`}>{s.status}</span>
              </div>
              <pre className="sp-mono mt-1.5 whitespace-pre-wrap break-all text-[11px] text-[var(--sp-ink-3)]">{JSON.stringify(s.input)}</pre>
              {(s.error ?? s.output) && <p className="mt-1 line-clamp-4 break-all text-[11.5px] text-[var(--sp-ink-4)]">{s.error ?? s.output}</p>}
            </li>
          ))}
        </ol>
      </ListState>
    </aside>
  );
}

function Incidents() {
  const incidents = useBrainGet<{ items: Incident[] }>("/v2/incidents?limit=50");
  const items = incidents.data?.items ?? [];
  return (
    <div className="px-6 py-4">
      <ListState loading={incidents.loading} error={incidents.error} empty={items.length === 0 && "Nothing went wrong lately."}>
        <table className="sp-table">
          <thead>
            <tr>
              <th>What happened</th>
              <th>Stage</th>
              <th>Outcome</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td>
                  <div className="text-[var(--sp-ink)]">{i.error}</div>
                  <div className="sp-mono mt-0.5 text-[11px] text-[var(--sp-ink-4)]">
                    {[i.engine_or_provider, i.remedy].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td className="sp-mono text-[12px]">{i.stage}</td>
                <td>{i.outcome && <Tag kind={i.outcome === "recovered" ? "done" : i.outcome === "degraded" ? "waiting" : "failed"} label={i.outcome.replaceAll("_", " ")} />}</td>
                <td className="whitespace-nowrap text-[12px] text-[var(--sp-ink-4)]">{ago(i.ts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ListState>
    </div>
  );
}
