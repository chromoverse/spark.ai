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
        const items = (res as any)?.items || [];
        setTasks(items);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, [user?._id]);

  const statusColor = (s: string) => {
    if (s === "completed") return "text-green-400";
    if (s === "failed") return "text-red-400";
    return "text-yellow-400";
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-4 border-b border-slate-800">
        <Clock size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Task History</h2>
        <span className="text-xs text-slate-500 ml-auto">{tasks.length} entries</span>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Clock size={32} className="mb-2 opacity-40" />
            <p>No task history yet</p>
            <p className="text-xs mt-1">Talk to Spark to see executions here</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((t) => (
              <div key={t.id} className="px-4 py-3 bg-slate-900/40 border border-slate-800 rounded-lg flex items-center justify-between">
                <div>
                  <span className="text-sm text-white font-medium">{t.tool_name || "task"}</span>
                  <span className={`ml-2 text-xs ${statusColor(t.status)}`}>{t.status}</span>
                  {t.duration_ms != null && <span className="ml-2 text-[11px] text-slate-600">{t.duration_ms}ms</span>}
                  {t.error && <p className="text-xs text-red-400/70 mt-0.5 truncate max-w-md">{t.error}</p>}
                </div>
                <span className="text-[11px] text-slate-600">{t.updated_at ? new Date(t.updated_at).toLocaleString() : ""}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
