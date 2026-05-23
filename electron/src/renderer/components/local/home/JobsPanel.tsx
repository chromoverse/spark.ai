import { Briefcase, Loader2, Check, X, Clock, AlertTriangle } from "lucide-react";
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
    <div className="w-64 border-l border-slate-800/50 bg-[#0a0a12] flex flex-col">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800/50">
        <Briefcase size={12} className="text-slate-400" />
        <h3 className="text-xs font-medium text-slate-300">Jobs</h3>
        {activeJobs.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 ml-auto">
            {activeJobs.length}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {activeJobs.map(job => (
          <JobCard key={job.job_id} job={job} />
        ))}
        {queuedJobs.map(job => (
          <JobCard key={job.job_id} job={job} />
        ))}
        {recentJobs.map(job => (
          <JobCard key={job.job_id} job={job} />
        ))}
      </div>
    </div>
  );
}

function JobCard({ job }: { job: JobInfo }) {
  const elapsed = Math.floor((Date.now() - job.started_at) / 1000);
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  const statusConfig = {
    running: { icon: Loader2, color: "text-blue-400", bg: "bg-blue-500/5 border-blue-500/15", label: elapsedStr, spin: true },
    replanning: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/5 border-amber-500/15", label: "Replanning", spin: false },
    queued: { icon: Clock, color: "text-slate-400", bg: "bg-slate-500/5 border-slate-500/15", label: `#${job.position || "?"}`, spin: false },
    completed: { icon: Check, color: "text-emerald-400", bg: "bg-emerald-500/5 border-emerald-500/10", label: "Done", spin: false },
    failed: { icon: X, color: "text-red-400", bg: "bg-red-500/5 border-red-500/10", label: "Failed", spin: false },
    cancelled: { icon: X, color: "text-slate-500", bg: "bg-slate-500/5 border-slate-500/10", label: "Cancelled", spin: false },
  };

  const cfg = statusConfig[job.status] || statusConfig.running;
  const Icon = cfg.icon;

  return (
    <div className={`rounded-lg border px-3 py-2 ${cfg.bg}`}>
      <div className="flex items-start gap-2">
        <Icon size={12} className={`${cfg.color} mt-0.5 shrink-0 ${cfg.spin ? "animate-spin" : ""}`} />
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-slate-200 leading-snug truncate">{job.goal}</p>
          <span className={`text-[10px] ${cfg.color}`}>{cfg.label}</span>
        </div>
      </div>
    </div>
  );
}
