import { Radio, Check, X, Loader2, Search, Globe, Sparkles, ChevronDown, ChevronUp } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";
import type { SparkLogPayload } from "@shared/socket.types";
import EntityCards, { type EntityCardData } from "@/components/local/home/EntityCards";

interface HomeLiveProps {
  entityResult?: { entities: EntityCardData[]; intent: string } | null;
  onEntityDismiss?: () => void;
}

// ─── Storage ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "spark_live_threads";
const STORAGE_VERSION_KEY = "spark_live_threads_v";
const STORAGE_VERSION = 4;  // Bump to clear stale thread data from old reducer logic
const MAX_THREADS = 50;

interface ToolStep {
  tool_name: string;
  task_id: string;
  status: "pending" | "running" | "completed" | "failed";
  latency_ms?: number;
  params_msg?: string;
  steps: string[];
  result_summary?: string;
  scraping_sites?: { url: string; domain: string }[];
}

interface Thread {
  id: string;
  timestamp: string;
  query: string;
  ai_response?: string;
  plan?: string[];
  job_id?: string;
  tools: ToolStep[];
  summary?: string;
  status: "thinking" | "planning" | "executing" | "completed" | "failed";
  entities?: EntityCardData[];
  entityIntent?: string;
}

function loadThreads(): Thread[] {
  try {
    // Clear stale data when schema version changes
    const v = localStorage.getItem(STORAGE_VERSION_KEY);
    if (v !== String(STORAGE_VERSION)) {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.setItem(STORAGE_VERSION_KEY, String(STORAGE_VERSION));
      return [];
    }
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveThreads(threads: Thread[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(threads.slice(-MAX_THREADS)));
  } catch { /* quota */ }
}

function timeLabel(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return "now";
  if (diff < 300_000) return `${Math.floor(diff / 60_000)}m`;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ─── Reducer ────────────────────────────────────────────────────────────────
//
// Thread-event correlation rules:
//   - query_received → always creates a new thread; closes stale thinking threads
//   - ai_response → targets the most recent thread WITHOUT an ai_response
//   - plan_created → targets the EARLIEST "thinking" thread without a plan
//   - task_running (new task_id) → targets executing thread whose plan has this tool
//   - subsequent tool events → strict task_id lookup, fallback to executing thread
//
// This prevents events from one query bleeding into another when rapid-fire
// voice commands create multiple threads before the first plan arrives.

function reduceLog(threads: Thread[], log: SparkLogPayload): Thread[] {
  const updated = [...threads];
  const payload = log.payload || {};

  // Strict task_id lookup — no fallback
  const findByTaskId = (taskId: string | undefined): Thread | undefined => {
    if (!taskId) return undefined;
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].tools.some(t => t.task_id === taskId)) return updated[i];
    }
    return undefined;
  };

  // Lookup by taskId and jobId
  const findByTaskIdAndJobId = (taskId: string | undefined, jobId: string | undefined): Thread | undefined => {
    if (!taskId) return undefined;
    if (jobId) {
      for (let i = updated.length - 1; i >= 0; i--) {
        if (updated[i].job_id === jobId && updated[i].tools.some(t => t.task_id === taskId)) return updated[i];
      }
    }
    // Fallback: match by taskId only
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].tools.some(t => t.task_id === taskId)) return updated[i];
    }
    return undefined;
  };

  // Most recent thread in "executing" state
  const findExecuting = (): Thread | undefined => {
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].status === "executing") return updated[i];
    }
    return undefined;
  };

  // Lookup by job_id
  const findByJobId = (jobId: string | undefined): Thread | undefined => {
    if (!jobId) return undefined;
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].job_id === jobId) return updated[i];
    }
    return undefined;
  };

  // Executing thread whose plan includes this tool name
  const findExecutingForTool = (toolName: string): Thread | undefined => {
    if (!toolName) return findExecuting();
    for (let i = updated.length - 1; i >= 0; i--) {
      const t = updated[i];
      if (t.status === "executing" && t.plan?.includes(toolName)) return t;
    }
    return findExecuting();
  };

  // Close conversation-only threads that are old enough to be stale.
  const closeStaleThinking = () => {
    let newestExecutingTs = "";
    for (const t of updated) {
      if ((t.status === "executing" || t.plan?.length) && t.timestamp > newestExecutingTs) {
        newestExecutingTs = t.timestamp;
      }
    }
    for (const t of updated) {
      if (
        t.status === "thinking" &&
        t.ai_response &&
        !t.plan?.length &&
        t.tools.length === 0 &&
        (newestExecutingTs && t.timestamp < newestExecutingTs)
      ) {
        t.status = "completed";
      }
    }
  };

  // Check if all tools in a thread are done
  const checkCompletion = (thread: Thread) => {
    if (thread.tools.length > 0 && thread.tools.every(t => t.status === "completed" || t.status === "failed")) {
      thread.status = thread.tools.some(t => t.status === "failed") ? "failed" : "completed";
    }
  };

  switch (log.event_type) {
    case "query_received": {
      closeStaleThinking();
      updated.push({
        id: `t_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        timestamp: log.timestamp,
        query: payload.query || payload.message || "",
        tools: [],
        status: "thinking",
      });
      break;
    }

    case "ai_response": {
      for (let i = updated.length - 1; i >= 0; i--) {
        if (!updated[i].ai_response) {
          updated[i].ai_response = payload.message || payload.text || "";
          break;
        }
      }
      break;
    }

    case "plan_created": {
      const planTools = payload.tools || (payload.message || "").split(", ").filter(Boolean);
      let matched: Thread | undefined;
      let matchedIdx = -1;

      if (payload.query) {
        const pq = (payload.query as string).trim().toLowerCase();
        for (let i = updated.length - 1; i >= 0; i--) {
          const t = updated[i];
          if (t.status === "thinking" && !t.plan?.length) {
            const tq = t.query.trim().toLowerCase();
            if (tq === pq || pq.startsWith(tq) || tq.startsWith(pq)) {
              matched = t;
              matchedIdx = i;
              break;
            }
          }
        }
      }

      if (!matched) {
        for (let i = 0; i < updated.length; i++) {
          if (updated[i].status === "thinking" && !updated[i].plan?.length) {
            matched = updated[i];
            matchedIdx = i;
            break;
          }
        }
      }

      if (matched) {
        matched.plan = planTools;
        matched.status = "executing";
        if (payload.job_id) matched.job_id = payload.job_id as string;
        for (let j = 0; j < matchedIdx; j++) {
          if (updated[j].status === "thinking" && updated[j].ai_response && !updated[j].plan?.length && updated[j].tools.length === 0) {
            updated[j].status = "completed";
          }
        }
      }
      break;
    }

    case "task_running": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      let thread = findByTaskIdAndJobId(log.task_id, jobId);
      if (!thread && jobId) thread = findByJobId(jobId);
      if (!thread) thread = findExecutingForTool(log.tool_name || "");
      if (thread) {
        if (jobId && !thread.job_id) {
          thread.job_id = jobId;
        }
        const existing = thread.tools.find(t => t.task_id === log.task_id);
        if (!existing) {
          thread.tools.push({
            tool_name: log.tool_name || "unknown",
            task_id: log.task_id || "",
            status: "running",
            steps: [],
          });
        } else {
          existing.status = "running";
        }
      }
      break;
    }

    case "tool_params": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === log.task_id);
        if (tool) tool.params_msg = payload.message || "";
      }
      break;
    }

    case "tool_step":
    case "tool_progress": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === log.task_id)
          || thread.tools.filter(t => t.status === "running").pop();
        if (tool) {
          if (payload.message && !tool.steps.includes(payload.message)) {
            tool.steps.push(payload.message);
          }
          if (payload.stage === "scraping" && Array.isArray(payload.urls)) {
            tool.scraping_sites = payload.urls;
          }
          if (payload.stage === "scrape_complete" || payload.stage === "extracting") {
            tool.scraping_sites = undefined;
          }
        }
      }
      break;
    }

    case "tool_invoked":
    case "task_completed": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === log.task_id);
        if (tool) {
          tool.status = (log.status === "success" || log.status === "completed") ? "completed" : "failed";
          tool.latency_ms = payload.latency_ms ?? payload.duration_ms;
          if (payload.result_summary) tool.result_summary = payload.result_summary;
        }
        checkCompletion(thread);
      }
      break;
    }

    case "tool_output": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === log.task_id)
          || thread.tools.filter(t => t.status === "running").pop();
        if (tool) {
          tool.status = payload.success ? "completed" : "failed";
          tool.latency_ms = payload.duration_ms || tool.latency_ms;
          if (payload.result_summary) tool.result_summary = payload.result_summary;
          if (!payload.success && payload.error) {
            tool.steps.push(payload.error);
          } else if (payload.message && !tool.steps.includes(payload.message) && !payload.result_summary) {
            tool.steps.push(payload.message);
          }
        }
        checkCompletion(thread);
      }
      break;
    }

    case "tool_failed": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === log.task_id);
        if (tool) {
          tool.status = "failed";
          tool.steps.push(payload.error || payload.message || "Unknown error");
        }
        checkCompletion(thread);
      }
      break;
    }

    case "execution_complete":
    case "summary": {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByJobId(jobId) || findByTaskIdAndJobId(log.task_id, jobId) || findExecuting();
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        for (const tool of thread.tools) {
          if (tool.status === "running" || tool.status === "pending") tool.status = "completed";
        }
        thread.status = thread.tools.some(t => t.status === "failed") ? "failed" : "completed";
        if (payload.message) thread.summary = payload.message;
      }
      break;
    }

    default: {
      const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
      const thread = findByTaskIdAndJobId(log.task_id, jobId) || (jobId && findByJobId(jobId)) || findExecuting();
      if (thread && payload.message) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const runningTool = thread.tools.filter(t => t.status === "running").pop();
        if (runningTool && !runningTool.steps.includes(payload.message)) {
          runningTool.steps.push(payload.message);
        }
      }
      break;
    }
  }

  return updated.slice(-MAX_THREADS);
}

// ─── Tool label ─────────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  web_research: "Research",
  web_search: "Search",
  web_scrape: "Scrape",
  current_location: "Location",
  file_create: "File",
  file_open: "Open",
  app_open: "App",
  ai_summarize: "Summary",
  shell_execute: "Shell",
  shell_agent: "Shell Agent",
  content_generate: "Generate",
  weather_current: "Weather",
  weather_forecast: "Forecast",
  email_list: "Inbox",
  email_send: "Send Email",
  email_read: "Read Email",
  screenshot_capture: "Screenshot",
  battery_status: "Battery",
  folder_organize: "Organize",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ─── Stage icon ─────────────────────────────────────────────────────────────

function StageIcon({ stage }: { stage: string }) {
  if (stage.includes("search")) return <Search size={10} className="text-blue-400" />;
  if (stage.includes("scrap")) return <Globe size={10} className="text-amber-400" />;
  if (stage.includes("extract")) return <Sparkles size={10} className="text-purple-400" />;
  return null;
}

// ─── Tool inline view ───────────────────────────────────────────────────────

function ToolInline({ tool }: { tool: ToolStep }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = tool.status === "running";
  const isFailed = tool.status === "failed";
  const isDone = tool.status === "completed";

  const latencyStr = tool.latency_ms != null
    ? tool.latency_ms < 1000 ? `${tool.latency_ms}ms` : `${(tool.latency_ms / 1000).toFixed(1)}s`
    : null;

  const statusDot = isRunning
    ? "bg-blue-400 animate-pulse"
    : isDone
      ? "bg-emerald-400"
      : isFailed
        ? "bg-red-400"
        : "bg-slate-600";

  // Show steps live while running; collapsed after completion (toggle to expand)
  const showSteps = isRunning || expanded;

  return (
    <div className="group">
      {/* Main row */}
      <div
        className="flex items-center gap-2 py-0.5 cursor-pointer"
        onClick={() => { if (!isRunning) setExpanded(e => !e); }}
      >
        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot}`} />
        <span className={`text-xs font-medium ${isFailed ? "text-red-400" : "text-slate-300"}`}>
          {toolLabel(tool.tool_name)}
        </span>
        {latencyStr && (
          <span className="text-[10px] text-slate-600 tabular-nums">{latencyStr}</span>
        )}

        {/* Spinner when running with no steps yet */}
        {isRunning && tool.steps.length === 0 && (
          <Loader2 size={10} className="text-blue-400 animate-spin" />
        )}

        {/* Expand/collapse toggle for completed tools with steps */}
        {!isRunning && tool.steps.length > 0 && (
          <span className="ml-auto">
            {expanded
              ? <ChevronUp size={12} className="text-slate-500" />
              : <ChevronDown size={12} className="text-slate-500" />
            }
          </span>
        )}
      </div>

      {/* Streaming steps — always visible while running, toggled after completion */}
      {showSteps && tool.steps.length > 0 && (
        <div className="ml-4 pb-1.5 space-y-0 border-l border-slate-800/50 pl-2">
          {tool.steps.map((step, i) => {
            const isLast = i === tool.steps.length - 1;
            return (
              <div key={i} className="flex items-start gap-1.5 py-0.5">
                <StageIcon stage={step} />
                <p className={`text-[10px] leading-relaxed ${
                  isRunning && isLast ? "text-blue-400" : "text-slate-500"
                }`}>
                  {step}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {/* Scraping sites */}
      {tool.scraping_sites && tool.scraping_sites.length > 0 && (
        <div className="ml-4 pb-1.5 flex flex-wrap gap-1">
          {tool.scraping_sites.map((site, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded bg-slate-800/60 px-1.5 py-0.5 text-[10px] text-slate-400">
              <img
                src={`https://www.google.com/s2/favicons?domain=${site.domain}&sz=16`}
                alt=""
                className="w-3 h-3 rounded-sm"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
              {site.domain}
            </span>
          ))}
        </div>
      )}

      {/* Result summary — always visible after completion */}
      {isDone && tool.result_summary && (
        <p className="ml-4 text-[11px] text-emerald-400/80 leading-relaxed pb-1">
          {tool.result_summary}
        </p>
      )}

      {/* Failed error */}
      {isFailed && tool.steps.length > 0 && (
        <p className="ml-4 text-[10px] text-red-400/70 pb-1">
          {tool.steps[tool.steps.length - 1]}
        </p>
      )}
    </div>
  );
}

// ─── Thread Component ───────────────────────────────────────────────────────

function ThreadView({ thread, onDismissEntities }: { thread: Thread; onDismissEntities?: () => void }) {
  const hasTools = thread.tools.length > 0 || (thread.plan && thread.plan.length > 0);
  const isActive = hasTools && (thread.status === "executing" || thread.status === "planning");
  const isDone = thread.status === "completed";
  const isFailed = thread.status === "failed";

  // Conversation-only threads — compact view
  if (!hasTools) {
    return (
      <div className="flex items-start gap-2.5 py-2 px-1">
        <div className={`w-5 h-5 rounded-full flex items-center justify-center mt-0.5 shrink-0 ${
          thread.status === "thinking" && !thread.ai_response
            ? "bg-blue-500/10"
            : "bg-slate-800/30"
        }`}>
          {thread.status === "thinking" && !thread.ai_response
            ? <Loader2 size={10} className="text-blue-400 animate-spin" />
            : <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
          }
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <p className="text-[12px] text-slate-300 leading-snug">{thread.query}</p>
            <span className="text-[10px] text-slate-700 shrink-0">{timeLabel(thread.timestamp)}</span>
          </div>
          {thread.ai_response && (
            <p className="text-[11px] text-cyan-400/50 mt-0.5 leading-snug">{thread.ai_response}</p>
          )}
        </div>
      </div>
    );
  }

  // Tool threads — full view
  return (
    <div className="py-2.5 px-1">
      <div className="flex items-start gap-2.5">
        {/* Status indicator */}
        <div className={`w-6 h-6 rounded-full flex items-center justify-center mt-0.5 shrink-0 ${
          isActive ? "bg-blue-500/15 ring-1 ring-blue-500/25" :
          isDone ? "bg-emerald-500/10" :
          isFailed ? "bg-red-500/10" :
          "bg-slate-800/40"
        }`}>
          {isActive ? <Loader2 size={11} className="text-blue-400 animate-spin" /> :
           isDone ? <Check size={11} className="text-emerald-400" /> :
           isFailed ? <X size={11} className="text-red-400" /> :
           <span className="w-2 h-2 rounded-full bg-slate-600" />}
        </div>

        <div className="flex-1 min-w-0">
          {/* Query */}
          <div className="flex items-baseline gap-2">
            <p className="text-[13px] text-white leading-snug font-medium">{thread.query}</p>
            <span className="text-[10px] text-slate-600 shrink-0">{timeLabel(thread.timestamp)}</span>
          </div>

          {/* AI response */}
          {thread.ai_response && (
            <p className="text-[11px] text-cyan-400/60 mt-0.5 leading-snug">{thread.ai_response}</p>
          )}

          {/* Plan pills */}
          {thread.plan && thread.plan.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap mt-1.5">
              {thread.plan.map((step, i) => {
                const toolState = thread.tools.find(t => t.tool_name === step);
                const pillColor = toolState?.status === "completed"
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                  : toolState?.status === "running"
                    ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                    : toolState?.status === "failed"
                      ? "bg-red-500/10 text-red-400 border-red-500/20"
                      : "bg-slate-800/40 text-slate-500 border-slate-700/30";
                return (
                  <span key={i} className={`text-[10px] px-1.5 py-0.5 rounded border ${pillColor}`}>
                    {toolLabel(step)}
                  </span>
                );
              })}
            </div>
          )}

          {/* Tools — inline progressive view */}
          {thread.tools.length > 0 && (
            <div className="mt-2 space-y-0.5">
              {thread.tools.map((tool, i) => (
                <ToolInline key={`${tool.task_id}_${i}`} tool={tool} />
              ))}
            </div>
          )}

          {/* Entity cards — inline below the thread that produced them */}
          {thread.entities && thread.entities.length > 0 && (
            <div className="mt-3">
              <EntityCards
                entities={thread.entities}
                intent={thread.entityIntent}
                onDismiss={() => onDismissEntities?.()}
              />
            </div>
          )}

          {/* Final summary */}
          {thread.summary && (
            <p className="text-[11px] text-slate-500 mt-1.5 leading-relaxed">
              {thread.summary}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export default function HomeLive({ entityResult, onEntityDismiss }: HomeLiveProps = {}) {
  const { on, off } = useSocket();
  const [threads, setThreads] = useState<Thread[]>(loadThreads);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Handle spark:log events (primary event stream)
  const handleLog = useCallback((data: SparkLogPayload) => {
    setThreads((prev) => {
      const next = reduceLog(prev, data);
      saveThreads(next);
      return next;
    });
  }, []);

  useEffect(() => {
    on("spark:log" as any, handleLog as any);
    return () => { off("spark:log" as any, handleLog as any); };
  }, [on, off, handleLog]);

  // Handle tool:output for entity cards and rich data (separate socket event with full data)
  useEffect(() => {
    const handler = (data: any) => {
      if (!data?.success || !data?.output?.data) return;
      const output = data.output;
      const toolData = output.data;
      const toolName = output.tool || "";

      console.log(`📡 [HomeLive] tool:output received — tool=${toolName} task_id=${output.task_id} job_id=${output.job_id}`, Object.keys(toolData));

      setThreads(prev => {
        const next = [...prev];
        const jobId = output.job_id;

        // ── Entity cards from web_research ──
        if (
          toolName === "web_research" &&
          toolData.result_type === "entities" &&
          Array.isArray(toolData.entities) &&
          toolData.entities.length > 0
        ) {
          let target: Thread | undefined;
          // Match by task_id and job_id first
          if (output.task_id) {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId && next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
            if (!target) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
          }
          // Match by job_id only if task_id wasn't matched
          if (!target && jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                target = next[i];
                break;
              }
            }
          }
          // Fallback: most recent thread with web_research tool that has no entities yet
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research") && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          // Last resort: most recent thread with web_research in plan
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].plan?.includes("web_research") && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          // Absolute last resort: most recent thread with any tools and no entities
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.length > 0 && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          if (target) {
            console.log(`📡 [HomeLive] Attaching ${toolData.entities.length} entities to thread: ${target.query.slice(0, 40)}`);
            target.entities = toolData.entities;
            target.entityIntent = toolData.intent || "results";
          } else {
            console.warn("📡 [HomeLive] No matching thread found for entity data — threads:", next.map(t => ({ q: t.query.slice(0, 30), tools: t.tools.map(x => x.tool_name), entities: !!t.entities?.length })));
          }
        }

        // ── Snippets from web_research (factual_lookup / gold price etc.) ──
        if (
          toolName === "web_research" &&
          toolData.result_type === "snippets" &&
          Array.isArray(toolData.snippets) &&
          toolData.snippets.length > 0
        ) {
          let target: Thread | undefined;
          if (output.task_id) {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId && next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
            if (!target) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
          }
          if (!target && jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                target = next[i];
                break;
              }
            }
          }
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research")) {
                target = next[i];
                break;
              }
            }
          }
          if (target) {
            const tool = target.tools.find((t: ToolStep) => t.task_id === output.task_id)
              || target.tools.find((t: ToolStep) => t.tool_name === "web_research");
            if (tool && !tool.result_summary) {
              const firstSnippet = toolData.snippets[0];
              tool.result_summary = typeof firstSnippet === "string"
                ? firstSnippet.slice(0, 200)
                : (firstSnippet?.snippet || firstSnippet?.text || "").slice(0, 200);
            }
          }
        }

        // ── Update tool status for any tool output with task_id ──
        if (output.task_id) {
          let matched = false;
          if (jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                const tool = next[i].tools.find((t: ToolStep) => t.task_id === output.task_id);
                if (tool) {
                  if (tool.status === "running" || tool.status === "pending") {
                    tool.status = "completed";
                  }
                  matched = true;
                  break;
                }
              }
            }
          }
          if (!matched) {
            for (let i = next.length - 1; i >= 0; i--) {
              const tool = next[i].tools.find((t: ToolStep) => t.task_id === output.task_id);
              if (tool) {
                if (tool.status === "running" || tool.status === "pending") {
                  tool.status = "completed";
                }
                break;
              }
            }
          }
        }

        saveThreads(next);
        return next;
      });
    };

    on("tool:output" as any, handler as any);
    return () => { off("tool:output" as any, handler as any); };
  }, [on, off]);

  // Fallback: attach entityResult prop to the correct thread
  useEffect(() => {
    if (!entityResult?.entities?.length) return;
    // Capture narrowed values — TS can't carry narrowing into closures
    const entities = entityResult.entities;
    const intent = entityResult.intent;
    setThreads(prev => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research") && !next[i].entities?.length) {
          next[i].entities = entities;
          next[i].entityIntent = intent;
          saveThreads(next);
          break;
        }
      }
      return next;
    });
  }, [entityResult]);

  // Periodically close stale "thinking" threads that are conversation-only.
  // Handles the case where a conversation thread is the LAST one — no future
  // query_received will trigger closeStaleThinking, so it'd spin forever.
  useEffect(() => {
    const interval = setInterval(() => {
      setThreads(prev => {
        const now = Date.now();
        let changed = false;
        const next = prev.map(t => {
          if (
            t.status === "thinking" &&
            t.ai_response &&
            !t.plan?.length &&
            t.tools.length === 0 &&
            now - new Date(t.timestamp).getTime() > 8000
          ) {
            changed = true;
            return { ...t, status: "completed" as const };
          }
          return t;
        });
        if (changed) saveThreads(next);
        return changed ? next : prev;
      });
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [threads]);

  const clearLogs = useCallback(() => {
    setThreads([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  // Only count threads with tools in active state
  const activeCount = threads.filter(t =>
    (t.status === "executing" || t.status === "planning") &&
    (t.plan?.length || t.tools.length)
  ).length;

  const dismissEntities = useCallback((threadId: string) => {
    setThreads(prev => {
      const next = [...prev];
      const t = next.find(x => x.id === threadId);
      if (t) {
        t.entities = undefined;
        t.entityIntent = undefined;
        saveThreads(next);
      }
      return next;
    });
    onEntityDismiss?.();
  }, [onEntityDismiss]);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-6 py-3 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Radio size={10} className={`${activeCount > 0 ? "text-blue-400 animate-pulse" : "text-emerald-400"}`} />
          <h2 className="text-sm font-medium text-white">Activity</h2>
          {activeCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
              {activeCount} active
            </span>
          )}
        </div>
        {threads.length > 0 && (
          <button onClick={clearLogs} className="text-[10px] text-slate-600 ml-auto hover:text-slate-400 transition-colors">
            Clear
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-2">
        {threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600">
            <Radio size={20} className="mb-2 opacity-15" />
            <p className="text-xs">Listening for commands</p>
          </div>
        ) : (
          <div>
            {threads.map((thread, i) => (
              <div key={thread.id}>
                {i > 0 && <div className="border-t border-slate-800/30 mx-1" />}
                <ThreadView
                  thread={thread}
                  onDismissEntities={() => dismissEntities(thread.id)}
                />
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
