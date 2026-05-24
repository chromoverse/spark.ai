import { Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { useAppSelector } from "@/store/hooks";
import axiosInstance from "@/utils/axiosConfig";

interface TaskEntry {
  id: string;
  tool_name: string;
  status: string;
  updated_at: string;
  duration_ms?: number;
  error?: string;
}

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export default function History() {
  const { user } = useAppSelector((state) => state.auth);
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?._id) return;
    (async () => {
      try {
        const res = await axiosInstance.get(`/kernel/user-history?user_id=${user._id}&limit=50`, { baseURL: BASE });
        setTasks((res as any)?.items || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  const statusColor = (s: string): string => {
    if (s === "completed" || s === "success") return "var(--sp-ok)";
    if (s === "failed" || s === "error") return "var(--sp-err)";
    return "var(--sp-warn)";
  };

  // Group by date
  const grouped: Record<string, TaskEntry[]> = {};
  for (const t of tasks) {
    const day = t.updated_at ? new Date(t.updated_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }) : "Unknown";
    (grouped[day] ??= []).push(t);
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Clock size={15} style={{ color: "var(--sp-info)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>History</h2>
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: "auto" }}>{tasks.length} entries</span>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {loading ? (
          <SpinnerCenter />
        ) : tasks.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
            <Clock size={28} strokeWidth={1.2} style={{ opacity: 0.3 }} />
            <p className="sp-mono" style={{ fontSize: 13 }}>No task history yet</p>
            <p className="sp-mono" style={{ fontSize: 11 }}>Talk to Spark to see executions here</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 720 }}>
            {Object.entries(grouped).map(([day, items]) => (
              <div key={day}>
                <p className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8, padding: "0 2px" }}>
                  {day}
                </p>
                <div style={{ borderLeft: "2px solid var(--sp-line)", paddingLeft: 14, marginLeft: 2, display: "flex", flexDirection: "column", gap: 4 }}>
                  {items.map((t) => (
                    <div key={t.id} style={{ padding: "9px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13, color: "var(--sp-ink)", fontWeight: 500 }}>{t.tool_name || "task"}</span>
                        <span className="sp-mono" style={{ fontSize: 10, color: statusColor(t.status) }}>{t.status}</span>
                        {t.duration_ms != null && <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>{t.duration_ms}ms</span>}
                        <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", marginLeft: "auto" }}>
                          {t.updated_at ? new Date(t.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                        </span>
                      </div>
                      {t.error && <p style={{ marginTop: 3, fontSize: 11, color: "var(--sp-err)", lineHeight: 1.4 }}>{t.error}</p>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
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
