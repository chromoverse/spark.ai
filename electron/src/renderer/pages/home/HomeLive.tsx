import { Home as HomeIcon, Radio, ChevronRight, Check, X, Loader2, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";
import type { SparkLogPayload } from "@shared/socket.types";

// ─── Persistent storage ──────────────────────────────────────────────────────

const STORAGE_KEY = "spark_live_threads";
const MAX_THREADS = 50;

interface ToolStep {
  tool_name: string;
  task_id: string;
  status: "pending" | "running" | "completed" | "failed";
  latency_ms?: number;
  params_msg?: string;
  steps: string[];  // live progress messages
}

interface Thread {
  id: string;
  timestamp: string;
  query: string;
  ai_response?: string;
  plan?: string[];
  tools: ToolStep[];
  summary?: string;
  status: "thinking" | "planning" | "executing" | "completed" | "failed";
}

function loadThreads(): Thread[] {
  try {
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
  if (diff < 60_000) return "Just now";
  if (diff < 300_000) return `${Math.floor(diff / 60_000)}m ago`;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ─── Reducer: merge spark:log events into threads ────────────────────────────

function reduceLog(threads: Thread[], log: SparkLogPayload): Thread[] {
  const updated = [...threads];
  const payload = log.payload || {};
  const last = () => updated[updated.length - 1];

  switch (log.event_type) {
    case "query_received": {
      updated.push({
        id: `thread_${Date.now()}`,
        timestamp: log.timestamp,
        query: payload.query || payload.message || "",
        tools: [],
        status: "thinking",
      });
      break;
    }
    case "ai_response": {
      if (last()) last().ai_response = payload.message || payload.text || "";
      break;
    }
    case "plan_created": {
      if (last()) {
        last().plan = payload.tools || (payload.message || "").split(", ").filter(Boolean);
        last().status = "executing";
      }
      break;
    }
    case "task_running": {
      if (last()) {
        const existing = last().tools.find(t => t.task_id === log.task_id);
        if (!existing) {
          last().tools.push({
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
      if (last()) {
        const tool = last().tools.find(t => t.task_id === log.task_id);
        if (tool) tool.params_msg = payload.message || "";
      }
      break;
    }
    case "tool_step":
    case "tool_progress": {
      if (last()) {
        const tool = last().tools.find(t => t.task_id === log.task_id) || last().tools[last().tools.length - 1];
        if (tool && payload.message) {
          tool.steps.push(payload.message);
        }
      }
      break;
    }
    case "tool_invoked":
    case "task_completed": {
      if (last()) {
        const tool = last().tools.find(t => t.task_id === log.task_id);
        if (tool) {
          tool.status = (log.status === "success" || log.status === "completed") ? "completed" : "failed";
          tool.latency_ms = payload.latency_ms ?? payload.duration_ms;
        }
        // Derive thread status from tool states
        const allDone = last().tools.length > 0 && last().tools.every(t => t.status === "completed" || t.status === "failed");
        if (allDone) {
          last().status = last().tools.some(t => t.status === "failed") ? "failed" : "completed";
        }
      }
      break;
    }
    case "tool_output": {
      if (last()) {
        const tool = last().tools.find(t => t.task_id === log.task_id) || last().tools[last().tools.length - 1];
        if (tool) {
          tool.status = payload.success ? "completed" : "failed";
          tool.latency_ms = payload.duration_ms || tool.latency_ms;
          if (!payload.success && payload.error) {
            tool.steps.push(`❌ ${payload.error}`);
          } else if (payload.message && !tool.steps.includes(payload.message)) {
            tool.steps.push(payload.message);
          }
        }
        // Derive thread status from tool states
        const allDone = last().tools.length > 0 && last().tools.every(t => t.status === "completed" || t.status === "failed");
        if (allDone) {
          last().status = last().tools.some(t => t.status === "failed") ? "failed" : "completed";
        }
      }
      break;
    }
    case "tool_failed": {
      if (last()) {
        const tool = last().tools.find(t => t.task_id === log.task_id);
        if (tool) {
          tool.status = "failed";
          const reason = payload.error || payload.message || "Unknown error";
          tool.steps.push(`❌ ${reason}`);
        }
        // Derive thread status from tool states
        const allDone = last().tools.length > 0 && last().tools.every(t => t.status === "completed" || t.status === "failed");
        if (allDone) {
          last().status = last().tools.some(t => t.status === "failed") ? "failed" : "completed";
        }
      }
      break;
    }
    case "execution_complete":
    case "summary": {
      if (last()) {
        last().status = last().tools.some(t => t.status === "failed") ? "failed" : "completed";
        if (payload.message) last().summary = payload.message;
      }
      break;
    }
    default: {
      // Generic step/log messages — attach to current tool or thread
      if (last() && payload.message) {
        const currentTool = last().tools[last().tools.length - 1];
        if (currentTool && currentTool.status === "running") {
          if (!currentTool.steps.includes(payload.message)) {
            currentTool.steps.push(payload.message);
          }
        }
      }
      break;
    }
  }

  return updated.slice(-MAX_THREADS);
}

// ─── Tool Step Component ─────────────────────────────────────────────────────

function ToolStepView({ tool }: { tool: ToolStep }) {
  const icon = tool.status === "completed" ? <Check size={12} className="text-green-400" /> :
               tool.status === "failed" ? <X size={12} className="text-red-400" /> :
               tool.status === "running" ? <Loader2 size={12} className="text-blue-400 animate-spin" /> :
               <ChevronRight size={12} className="text-slate-500" />;

  const borderColor = tool.status === "completed" ? "border-green-500/20" :
                      tool.status === "failed" ? "border-red-500/20" :
                      tool.status === "running" ? "border-blue-500/30" : "border-slate-700/30";

  return (
    <div className={`ml-4 pl-3 border-l-2 ${borderColor} py-1`}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-mono text-slate-200">{tool.tool_name}</span>
        {tool.latency_ms != null && (
          <span className="text-[10px] text-slate-500 ml-auto">{tool.latency_ms}ms</span>
        )}
      </div>
      {tool.params_msg && (
        <p className="text-[11px] text-slate-500 ml-5 font-mono truncate">{tool.params_msg}</p>
      )}
      {tool.steps.length > 0 && (
        <div className="ml-5 mt-0.5 space-y-0">
          {tool.steps.map((step, i) => (
            <p key={i} className="text-[11px] text-slate-400 leading-relaxed">
              <span className="text-slate-600 mr-1">›</span>{step}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Thread Component ────────────────────────────────────────────────────────

function ThreadView({ thread }: { thread: Thread }) {
  const statusBadge = thread.status === "completed" ? "bg-green-500/10 text-green-400 border-green-500/20" :
                      thread.status === "failed" ? "bg-red-500/10 text-red-400 border-red-500/20" :
                      thread.status === "executing" ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                      "bg-slate-700/30 text-slate-400 border-slate-600/30";

  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 overflow-hidden">
      {/* Query */}
      <div className="px-4 py-3 border-b border-slate-800/40">
        <div className="flex items-start gap-2">
          <div className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center mt-0.5 shrink-0">
            <span className="text-[10px]">👤</span>
          </div>
          <p className="text-sm text-white leading-relaxed">{thread.query}</p>
          <span className="text-[10px] text-slate-600 ml-auto shrink-0">{timeLabel(thread.timestamp)}</span>
        </div>
      </div>

      {/* AI Response (acknowledge) */}
      {thread.ai_response && (
        <div className="px-4 py-2 border-b border-slate-800/20">
          <div className="flex items-start gap-2">
            <div className="w-5 h-5 rounded-full bg-cyan-900/40 flex items-center justify-center mt-0.5 shrink-0">
              <Zap size={10} className="text-cyan-400" />
            </div>
            <p className="text-xs text-cyan-300/80 leading-relaxed">{thread.ai_response}</p>
          </div>
        </div>
      )}

      {/* Plan */}
      {thread.plan && thread.plan.length > 0 && (
        <div className="px-4 py-2 border-b border-slate-800/20">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-purple-400 font-medium uppercase tracking-wider">Plan</span>
            <span className="text-[11px] text-slate-500">{thread.plan.join(" → ")}</span>
          </div>
        </div>
      )}

      {/* Tool Execution Steps */}
      {thread.tools.length > 0 && (
        <div className="px-4 py-2 space-y-1">
          {thread.tools.map((tool, i) => (
            <ToolStepView key={`${tool.task_id}_${i}`} tool={tool} />
          ))}
        </div>
      )}

      {/* Summary / Final */}
      {thread.summary && (
        <div className="px-4 py-2 border-t border-slate-800/30">
          <p className="text-xs text-slate-400 leading-relaxed truncate">{thread.summary}</p>
        </div>
      )}

      {/* Status badge */}
      {thread.status !== "thinking" && (
        <div className="px-4 py-1.5 border-t border-slate-800/20 flex items-center">
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusBadge}`}>
            {thread.status === "executing" && "Running…"}
            {thread.status === "completed" && "Done"}
            {thread.status === "failed" && "Failed"}
            {thread.status === "planning" && "Planning…"}
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function HomeLive() {
  const { on, off } = useSocket();
  const [threads, setThreads] = useState<Thread[]>(loadThreads);
  const bottomRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [threads]);

  const clearLogs = useCallback(() => {
    setThreads([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-3 border-b border-slate-800">
        <HomeIcon size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Live Activity</h2>
        <Radio size={10} className="text-green-400 animate-pulse" />
        <span className="text-xs text-slate-500 ml-auto cursor-pointer hover:text-slate-300" onClick={clearLogs}>
          {threads.length} threads
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Radio size={32} className="mb-3 opacity-30 animate-pulse" />
            <p className="font-medium">Listening…</p>
            <p className="text-xs mt-1 text-slate-600">Talk to Spark to see real-time activity</p>
          </div>
        ) : (
          <div className="space-y-3">
            {threads.map((thread) => (
              <ThreadView key={thread.id} thread={thread} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
