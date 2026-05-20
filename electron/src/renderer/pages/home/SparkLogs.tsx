import { Activity, Radio, Server, Clock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAppSelector } from "@/store/hooks";
import { useSocket } from "@/context/socketContextProvider";
import axiosInstance from "@/utils/axiosConfig";
import type { SparkLogPayload } from "@shared/socket.types";

type Tab = "realtime" | "static" | "timeline";

const BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace("/api/v1", "");

// ─── Status badge ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status?: string }) {
  const cls =
    status === "completed" || status === "success"
      ? "bg-green-500/15 text-green-400"
      : status === "failed" || status === "error"
        ? "bg-red-500/15 text-red-400"
        : "bg-slate-700/50 text-slate-400";
  return status ? (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>
      {status}
    </span>
  ) : null;
}

// ─── Real-time log entry ─────────────────────────────────────────────────────

function LogRow({ log }: { log: SparkLogPayload }) {
  const latency = log.payload?.latency_ms;
  return (
    <div className="px-3 py-2 bg-slate-900/50 border border-slate-800/60 rounded-lg flex items-center gap-2 text-xs">
      <span className="text-blue-400 font-mono w-16 shrink-0">
        {new Date(log.timestamp).toLocaleTimeString()}
      </span>
      <span className="text-white font-medium truncate">
        {log.tool_name || log.event_type}
      </span>
      <StatusBadge status={log.status} />
      {latency != null && (
        <span className="text-slate-500 ml-auto">{latency}ms</span>
      )}
      {log.task_id && (
        <span className="text-slate-600 text-[10px]">{log.task_id}</span>
      )}
    </div>
  );
}

// ─── Real-time tab ───────────────────────────────────────────────────────────

function RealtimeTab() {
  const { on, off } = useSocket();
  const [logs, setLogs] = useState<SparkLogPayload[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (data: SparkLogPayload) => {
      setLogs((prev) => [...prev.slice(-199), data]);
    };
    on("spark:log" as any, handler as any);
    return () => { off("spark:log" as any, handler as any); };
  }, [on, off]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (logs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
        <Radio size={28} className="mb-2 opacity-40 animate-pulse" />
        <p>Waiting for live events…</p>
        <p className="text-xs mt-1">Talk to Spark to see real-time execution</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {logs.map((log, i) => (
        <LogRow key={i} log={log} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// ─── Static logs tab (fetched from API, also updated via WS) ─────────────────

function StaticTab() {
  const { user } = useAppSelector((s) => s.auth);
  const { on, off } = useSocket();
  const [logs, setLogs] = useState<SparkLogPayload[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?._id) return;
    (async () => {
      try {
        const res = await axiosInstance.get(
          `/kernel/user-logs?user_id=${user._id}&limit=100`,
          { baseURL: BASE },
        );
        const items = (res as any)?.logs || [];
        setLogs(items);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  // Also append new WS events
  useEffect(() => {
    const handler = (data: SparkLogPayload) => {
      setLogs((prev) => [...prev, data].slice(-200));
    };
    on("spark:log" as any, handler as any);
    return () => { off("spark:log" as any, handler as any); };
  }, [on, off]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (logs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
        <Activity size={28} className="mb-2 opacity-40" />
        <p>No logs yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {logs.map((log, i) => (
        <LogRow key={i} log={log} />
      ))}
    </div>
  );
}

// ─── Server timeline tab ─────────────────────────────────────────────────────

interface TimelineEntry {
  id: string;
  tool_name: string;
  status: string;
  updated_at: string;
  duration_ms?: number;
  error?: string;
}

function TimelineTab() {
  const { user } = useAppSelector((s) => s.auth);
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?._id) return;
    (async () => {
      try {
        const res = await axiosInstance.get(
          `/kernel/user-history?user_id=${user._id}&limit=80`,
          { baseURL: BASE },
        );
        setEntries((res as any)?.items || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
        <Server size={28} className="mb-2 opacity-40" />
        <p>No execution history</p>
      </div>
    );
  }

  // Group by date
  const grouped: Record<string, TimelineEntry[]> = {};
  for (const e of entries) {
    const day = e.updated_at
      ? new Date(e.updated_at).toLocaleDateString()
      : "Unknown";
    (grouped[day] ??= []).push(e);
  }

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([day, items]) => (
        <div key={day}>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 px-1">
            {day}
          </div>
          <div className="space-y-1 border-l-2 border-slate-800 pl-3 ml-1">
            {items.map((e) => (
              <div
                key={e.id}
                className="px-3 py-2 bg-slate-900/40 border border-slate-800/60 rounded-lg"
              >
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-white font-medium">
                    {e.tool_name}
                  </span>
                  <StatusBadge status={e.status} />
                  {e.duration_ms != null && (
                    <span className="text-slate-500">{e.duration_ms}ms</span>
                  )}
                  <span className="text-slate-600 ml-auto text-[10px]">
                    {e.updated_at
                      ? new Date(e.updated_at).toLocaleTimeString()
                      : ""}
                  </span>
                </div>
                {e.error && (
                  <p className="text-[11px] text-red-400/70 mt-1 truncate">
                    {e.error}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: typeof Activity }[] = [
  { id: "realtime", label: "Live", icon: Radio },
  { id: "static", label: "Logs", icon: Activity },
  { id: "timeline", label: "Timeline", icon: Clock },
];

export default function SparkLogs() {
  const [tab, setTab] = useState<Tab>("realtime");

  return (
    <div className="h-full flex flex-col">
      {/* Header with tabs */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-slate-800">
        <Activity size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Spark Logs</h2>
        <div className="flex gap-1 ml-4">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors ${
                tab === id
                  ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-white hover:bg-slate-800/60"
              }`}
            >
              <Icon size={12} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {tab === "realtime" && <RealtimeTab />}
        {tab === "static" && <StaticTab />}
        {tab === "timeline" && <TimelineTab />}
      </div>
    </div>
  );
}
