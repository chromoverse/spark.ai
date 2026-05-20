import { Home as HomeIcon, Radio } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";
import type { SparkLogPayload } from "@shared/socket.types";

// ─── Persistent storage ──────────────────────────────────────────────────────

const STORAGE_KEY = "spark_live_logs";
const MAX_STORED = 500;

function loadLogs(): SparkLogPayload[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveLogs(logs: SparkLogPayload[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(logs.slice(-MAX_STORED)));
  } catch { /* quota */ }
}

// ─── Time grouping ──────────────────────────────────────────────────────────

function timeLabel(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return "Just now";
  if (diff < 300_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function dayKey(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "Today";
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

// ─── Merge logic: update existing task entries in-place ──────────────────────

interface DisplayEntry {
  id: string;
  event_type: string;
  tool_name?: string;
  status?: string;
  timestamp: string;
  message?: string;
  query?: string;
  latency_ms?: number;
  task_id?: string;
}

function mergeLog(entries: DisplayEntry[], log: SparkLogPayload): DisplayEntry[] {
  const payload = log.payload || {};
  const newEntry: DisplayEntry = {
    id: log.task_id || `${log.event_type}_${log.timestamp}`,
    event_type: log.event_type,
    tool_name: log.tool_name,
    status: log.status,
    timestamp: log.timestamp,
    message: payload.message,
    query: payload.query,
    latency_ms: payload.latency_ms,
    task_id: log.task_id,
  };

  // For task events, update existing entry in-place instead of adding new row
  if (log.task_id && (log.event_type === "tool_invoked" || log.event_type === "tool_failed" || log.event_type === "task_completed")) {
    const idx = entries.findLastIndex((e) => e.task_id === log.task_id);
    if (idx !== -1) {
      const updated = [...entries];
      updated[idx] = { ...updated[idx], status: log.status || newEntry.status, latency_ms: payload.latency_ms, message: payload.message || updated[idx].message };
      return updated;
    }
  }

  return [...entries, newEntry].slice(-MAX_STORED);
}

// ─── Entry component ─────────────────────────────────────────────────────────

function EntryRow({ entry }: { entry: DisplayEntry }) {
  const isQuery = entry.event_type === "query_received";
  const isPlan = entry.event_type === "plan_created";
  const isTask = entry.event_type === "task_running" || entry.event_type === "tool_invoked" || entry.event_type === "tool_failed" || entry.event_type === "task_completed";
  const isResponse = entry.event_type === "ai_response";

  const statusColor =
    entry.status === "success" || entry.status === "completed" ? "text-green-400 border-green-500/20 bg-green-500/5" :
    entry.status === "failed" || entry.status === "error" ? "text-red-400 border-red-500/20 bg-red-500/5" :
    entry.status === "running" ? "text-blue-400 border-blue-500/20 bg-blue-500/5" :
    "text-slate-400 border-slate-700/50 bg-slate-800/30";

  const statusIcon =
    entry.status === "success" || entry.status === "completed" ? "✓" :
    entry.status === "failed" || entry.status === "error" ? "✗" :
    entry.status === "running" ? "⟳" : "•";

  return (
    <div className={`px-3 py-2 rounded-lg border text-xs ${statusColor} transition-all duration-300`}>
      <div className="flex items-center gap-2">
        <span className="text-[11px] w-4 text-center">{statusIcon}</span>
        {isQuery && <span className="text-white font-medium">Query</span>}
        {isPlan && <span className="text-purple-300 font-medium">Plan</span>}
        {isTask && <span className="text-white font-medium">{entry.tool_name?.replace(/_/g, " ")}</span>}
        {isResponse && <span className="text-cyan-300 font-medium">Spark</span>}
        {!isQuery && !isPlan && !isTask && !isResponse && (
          <span className="text-white font-medium">{entry.tool_name || entry.event_type.replace(/_/g, " ")}</span>
        )}
        {entry.latency_ms != null && (
          <span className="text-slate-500 ml-auto">{entry.latency_ms}ms</span>
        )}
        <span className="text-slate-600 text-[10px] ml-auto">{timeLabel(entry.timestamp)}</span>
      </div>
      {entry.query && (
        <p className="text-slate-300 mt-1 pl-6 truncate">"{entry.query}"</p>
      )}
      {entry.message && !entry.query && (
        <p className="text-slate-400 mt-0.5 pl-6 truncate">{entry.message}</p>
      )}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function HomeLive() {
  const { on, off } = useSocket();
  const [entries, setEntries] = useState<DisplayEntry[]>(() => {
    // Rebuild display entries from stored logs
    const stored = loadLogs();
    let display: DisplayEntry[] = [];
    for (const log of stored) {
      display = mergeLog(display, log);
    }
    return display;
  });
  const rawLogsRef = useRef<SparkLogPayload[]>(loadLogs());
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleLog = useCallback((data: SparkLogPayload) => {
    rawLogsRef.current = [...rawLogsRef.current.slice(-MAX_STORED + 1), data];
    saveLogs(rawLogsRef.current);
    setEntries((prev) => mergeLog(prev, data));
  }, []);

  useEffect(() => {
    on("spark:log" as any, handleLog as any);
    return () => { off("spark:log" as any, handleLog as any); };
  }, [on, off, handleLog]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  // Group by day
  const grouped: Record<string, DisplayEntry[]> = {};
  for (const e of entries) {
    const key = dayKey(e.timestamp);
    (grouped[key] ??= []).push(e);
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-3 border-b border-slate-800">
        <HomeIcon size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Live Activity</h2>
        <Radio size={10} className="text-green-400 animate-pulse" />
        <span className="text-xs text-slate-500 ml-auto">{entries.length} events</span>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Radio size={32} className="mb-3 opacity-30 animate-pulse" />
            <p className="font-medium">Listening…</p>
            <p className="text-xs mt-1 text-slate-600">Talk to Spark to see real-time activity</p>
          </div>
        ) : (
          <div className="space-y-4">
            {Object.entries(grouped).map(([day, items]) => (
              <div key={day}>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 px-1 font-medium">{day}</div>
                <div className="space-y-1">
                  {items.map((entry, i) => (
                    <EntryRow key={`${entry.id}_${i}`} entry={entry} />
                  ))}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
