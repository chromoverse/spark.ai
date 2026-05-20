import { Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import axiosInstance from "@/utils/axiosConfig";

interface ToolEntry {
  name: string;
  description: string;
  category: string;
  execution_target: string;
  example_triggers?: string[];
}

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await axiosInstance.get("/kernel/tools", { baseURL: BASE });
        setTools(res?.data?.tools || (res as any)?.tools || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-full"><div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-4 border-b border-slate-800">
        <Wrench size={16} className="text-purple-400" />
        <h2 className="text-sm font-semibold text-white">Tools</h2>
        <span className="text-xs text-slate-500 ml-auto">{tools.length} registered</span>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
        {tools.map((t) => (
          <div key={t.name} className="px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-sm text-white font-medium">{t.name}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-400">{t.category}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">{t.execution_target}</span>
            </div>
            <p className="text-[11px] text-slate-500 mt-1 truncate">{t.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
