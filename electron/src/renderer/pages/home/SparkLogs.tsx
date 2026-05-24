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

function StatusDot({ status }: { status?: string }) {
  const color = status === "completed" || status === "success" ? "var(--sp-ok)"
    : status === "failed" || status === "error" ? "var(--sp-err)"
    : "var(--sp-ink-4)";
  if (!status) return null;
  return (
    <span className="sp-mono" style={{ fontSize: 10, color, padding: "1px 6px", borderRadius: 4, background: color + "22", border: `1px solid ${color}33` }}>
      {status}
    </span>
  );
}

function LogRow({ log }: { log: SparkLogPayload }) {
  const latency = log.payload?.latency_ms;
  return (
    <div style={{ padding: "8px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7, display: "flex", alignItems: "center", gap: 8 }}>
      <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-info)", flexShrink: 0, width: 58 }}>
        {new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
      <span style={{ fontSize: 13, color: "var(--sp-ink)", fontWeight: 500, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {log.tool_name || log.event_type}
      </span>
      <StatusDot status={log.status} />
      {latency != null && (
        <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", flexShrink: 0 }}>{latency}ms</span>
      )}
    </div>
  );
}

function RealtimeTab() {
  const { on, off } = useSocket();
  const [logs, setLogs] = useState<SparkLogPayload[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handler = useCallback((data: SparkLogPayload) => {
    setLogs((prev) => [...prev.slice(-199), data]);
  }, []);

  useEffect(() => {
    on("spark:log" as any, handler as any);
    return () => { off("spark:log" as any, handler as any); };
  }, [on, off, handler]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (logs.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
        <Radio size={26} strokeWidth={1.2} style={{ opacity: 0.35 }} className="animate-pulse" />
        <p className="sp-mono" style={{ fontSize: 13 }}>Waiting for live events…</p>
        <p className="sp-mono" style={{ fontSize: 11 }}>Talk to Spark to see real-time execution</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {logs.map((log, i) => <LogRow key={i} log={log} />)}
      <div ref={bottomRef} />
    </div>
  );
}

function StaticTab() {
  const { user } = useAppSelector((s) => s.auth);
  const { on, off } = useSocket();
  const [logs, setLogs] = useState<SparkLogPayload[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?._id) return;
    (async () => {
      try {
        const res = await axiosInstance.get(`/kernel/user-logs?user_id=${user._id}&limit=100`, { baseURL: BASE });
        setLogs((res as any)?.logs || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  useEffect(() => {
    const h = (data: SparkLogPayload) => setLogs((prev) => [...prev, data].slice(-200));
    on("spark:log" as any, h as any);
    return () => { off("spark:log" as any, h as any); };
  }, [on, off]);

  if (loading) return <SpinnerCenter />;
  if (logs.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
        <Activity size={26} strokeWidth={1.2} style={{ opacity: 0.35 }} />
        <p className="sp-mono" style={{ fontSize: 13 }}>No logs yet</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {logs.map((log, i) => <LogRow key={i} log={log} />)}
    </div>
  );
}

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
        const res = await axiosInstance.get(`/kernel/user-history?user_id=${user._id}&limit=80`, { baseURL: BASE });
        setEntries((res as any)?.items || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  if (loading) return <SpinnerCenter />;
  if (entries.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
        <Server size={26} strokeWidth={1.2} style={{ opacity: 0.35 }} />
        <p className="sp-mono" style={{ fontSize: 13 }}>No execution history</p>
      </div>
    );
  }

  const grouped: Record<string, TimelineEntry[]> = {};
  for (const e of entries) {
    const day = e.updated_at ? new Date(e.updated_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }) : "Unknown";
    (grouped[day] ??= []).push(e);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {Object.entries(grouped).map(([day, items]) => (
        <div key={day}>
          <p className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8, padding: "0 2px" }}>
            {day}
          </p>
          <div style={{ borderLeft: "2px solid var(--sp-line)", paddingLeft: 14, marginLeft: 2, display: "flex", flexDirection: "column", gap: 4 }}>
            {items.map((e) => (
              <div key={e.id} style={{ padding: "8px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, color: "var(--sp-ink)", fontWeight: 500 }}>{e.tool_name}</span>
                  <StatusDot status={e.status} />
                  {e.duration_ms != null && <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>{e.duration_ms}ms</span>}
                  <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", marginLeft: "auto" }}>
                    {e.updated_at ? new Date(e.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                  </span>
                </div>
                {e.error && <p style={{ marginTop: 3, fontSize: 11, color: "var(--sp-err)", lineHeight: 1.4 }}>{e.error}</p>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

const TABS: { id: Tab; label: string; icon: typeof Activity }[] = [
  { id: "realtime", label: "Live",     icon: Radio },
  { id: "static",   label: "Logs",     icon: Activity },
  { id: "timeline", label: "Timeline", icon: Clock },
];

export default function SparkLogs() {
  const [tab, setTab] = useState<Tab>("realtime");

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Activity size={15} style={{ color: "var(--sp-accent)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Spark Logs</h2>
        <div style={{ display: "flex", gap: 4, marginLeft: 16 }}>
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                padding: "4px 10px", borderRadius: 6,
                background: tab === id ? "var(--sp-accent-soft)" : "transparent",
                color: tab === id ? "var(--sp-accent)" : "var(--sp-ink-3)",
                border: tab === id ? "1px solid rgba(217,119,87,0.18)" : "1px solid transparent",
                fontSize: 12, cursor: "pointer", transition: "all 120ms",
              }}
            >
              <Icon size={11} />
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {tab === "realtime" && <RealtimeTab />}
        {tab === "static"   && <StaticTab />}
        {tab === "timeline" && <TimelineTab />}
      </div>
    </div>
  );
}

function SpinnerCenter() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
      <div style={{ width: 18, height: 18, border: "2px solid var(--sp-line-2)", borderTopColor: "var(--sp-accent)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </div>
  );
}
