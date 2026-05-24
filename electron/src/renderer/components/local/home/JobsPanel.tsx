import { BriefcaseBusiness, Loader2, Check, X, Clock, AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";

interface JobInfo {
  job_id: string;
  goal: string;
  status: "running" | "completed" | "failed" | "queued" | "replanning" | "cancelled";
  started_at: number;
  position?: number;
}

export default function JobsPanel() {
  const { on, off } = useSocket();
  const [jobs, setJobs] = useState<JobInfo[]>([]);

  const updateJob = useCallback((job_id: string, updates: Partial<JobInfo>) => {
    setJobs(prev => {
      const idx = prev.findIndex(j => j.job_id === job_id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], ...updates };
        return next;
      }
      if (updates.goal) {
        return [...prev, { job_id, goal: updates.goal, status: "running", started_at: Date.now(), ...updates }];
      }
      return prev;
    });
  }, []);

  useEffect(() => {
    const onStarted = (data: { job_id: string; goal: string }) => {
      updateJob(data.job_id, { goal: data.goal, status: "running", started_at: Date.now() });
    };
    const onCompleted = (data: { job_id: string }) => {
      updateJob(data.job_id, { status: "completed" });
    };
    const onFailed = (data: { job_id: string }) => {
      updateJob(data.job_id, { status: "failed" });
    };
    const onQueued = (data: { job_id: string; goal: string; position: number }) => {
      updateJob(data.job_id, { goal: data.goal, status: "queued", position: data.position });
    };
    const onReplanning = (data: { job_id: string }) => {
      updateJob(data.job_id, { status: "replanning" });
    };
    const onResumed = (data: { job_id: string }) => {
      updateJob(data.job_id, { status: "running" });
    };

    on("job:started" as any, onStarted as any);
    on("job:completed" as any, onCompleted as any);
    on("job:failed" as any, onFailed as any);
    on("job:queued" as any, onQueued as any);
    on("job:replanning" as any, onReplanning as any);
    on("job:resumed" as any, onResumed as any);

    return () => {
      off("job:started" as any, onStarted as any);
      off("job:completed" as any, onCompleted as any);
      off("job:failed" as any, onFailed as any);
      off("job:queued" as any, onQueued as any);
      off("job:replanning" as any, onReplanning as any);
      off("job:resumed" as any, onResumed as any);
    };
  }, [on, off, updateJob]);

  // Auto-remove completed/failed jobs after 60s
  useEffect(() => {
    const interval = setInterval(() => {
      setJobs(prev => prev.filter(j => {
        if (j.status === "completed" || j.status === "failed" || j.status === "cancelled") {
          return Date.now() - j.started_at < 60_000;
        }
        return true;
      }));
    }, 10_000);
    return () => clearInterval(interval);
  }, []);

  const activeJobs = jobs.filter(j => j.status === "running" || j.status === "replanning");
  const queuedJobs = jobs.filter(j => j.status === "queued");
  const recentJobs = jobs.filter(j => j.status === "completed" || j.status === "failed");

  if (jobs.length === 0) return null;

  return (
    <div style={{
      width: 224,
      flexShrink: 0,
      borderLeft: "1px solid var(--sp-line)",
      background: "var(--sp-bg)",
      display: "flex",
      flexDirection: "column",
      fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: "14px 16px 12px",
        borderBottom: "1px solid var(--sp-line)",
        display: "flex", alignItems: "center", gap: 8,
        flexShrink: 0,
      }}>
        <BriefcaseBusiness size={13} style={{ color: "var(--sp-ink-3)" }} />
        <span className="sp-mono" style={{
          fontSize: 10, color: "var(--sp-ink-4)",
          letterSpacing: "0.12em", textTransform: "uppercase", flex: 1,
        }}>
          Jobs
        </span>
        {activeJobs.length > 0 && (
          <span className="sp-mono" style={{
            fontSize: 10, color: "var(--sp-accent)",
            background: "var(--sp-accent-soft)",
            border: "1px solid rgba(217,119,87,0.18)",
            padding: "1px 7px", borderRadius: 99,
          }}>
            {activeJobs.length}
          </span>
        )}
      </div>

      {/* Job list */}
      <div
        className="sp-scroll"
        style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6 }}
      >
        {activeJobs.length > 0 && (
          <div style={{ marginBottom: 2 }}>
            <p className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 5, padding: "0 2px" }}>
              Running
            </p>
            {activeJobs.map(job => <JobCard key={job.job_id} job={job} />)}
          </div>
        )}
        {queuedJobs.length > 0 && (
          <div style={{ marginBottom: 2 }}>
            <p className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 5, padding: "0 2px" }}>
              Queued
            </p>
            {queuedJobs.map(job => <JobCard key={job.job_id} job={job} />)}
          </div>
        )}
        {recentJobs.length > 0 && (
          <div>
            <p className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 5, padding: "0 2px" }}>
              Recent
            </p>
            {recentJobs.map(job => <JobCard key={job.job_id} job={job} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function JobCard({ job }: { job: JobInfo }) {
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    if (job.status !== "running" && job.status !== "replanning") return;
    const t = setInterval(() => forceUpdate(n => n + 1), 1000);
    return () => clearInterval(t);
  }, [job.status]);

  const elapsed = Math.floor((Date.now() - job.started_at) / 1000);
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  type StatusKey = JobInfo["status"];
  const statusConfig: Record<StatusKey, {
    icon: React.ComponentType<{ size?: number; className?: string }>;
    color: string;
    bg: string;
    border: string;
    label: string;
    spin?: boolean;
  }> = {
    running:    { icon: Loader2,       color: "var(--sp-info)",   bg: "var(--sp-info-soft)",          border: "rgba(135,167,196,0.20)", label: elapsedStr, spin: true },
    replanning: { icon: AlertTriangle, color: "var(--sp-warn)",   bg: "rgba(212,160,74,0.07)",        border: "rgba(212,160,74,0.18)", label: "Replanning" },
    queued:     { icon: Clock,         color: "var(--sp-ink-3)",  bg: "transparent",                  border: "var(--sp-line)", label: `#${job.position ?? "?"}` },
    completed:  { icon: Check,         color: "var(--sp-ok)",     bg: "var(--sp-ok-soft)",            border: "rgba(127,182,133,0.20)", label: "Done" },
    failed:     { icon: X,             color: "var(--sp-err)",    bg: "var(--sp-err-soft)",           border: "rgba(201,112,100,0.20)", label: "Failed" },
    cancelled:  { icon: X,             color: "var(--sp-ink-4)",  bg: "transparent",                  border: "var(--sp-line)", label: "Cancelled" },
  };

  const cfg = statusConfig[job.status] || statusConfig.running;
  const Icon = cfg.icon;

  return (
    <div style={{
      borderRadius: 8,
      border: `1px solid ${cfg.border}`,
      background: cfg.bg,
      padding: "9px 11px",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <span style={{ color: cfg.color, display: "flex", flexShrink: 0, marginTop: 1 }}>
          <Icon size={12} className={cfg.spin ? "animate-spin" : undefined} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            fontSize: 12, color: "var(--sp-ink-2)", lineHeight: 1.45,
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
            overflow: "hidden",
            margin: 0,
          }}>
            {job.goal}
          </p>
          <span className="sp-mono" style={{ fontSize: 10, color: cfg.color, marginTop: 3, display: "block" }}>
            {cfg.label}
          </span>
        </div>
      </div>
    </div>
  );
}
