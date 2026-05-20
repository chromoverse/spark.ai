import { Puzzle } from "lucide-react";
import { useEffect, useState } from "react";
import axiosInstance from "@/utils/axiosConfig";

interface PluginEntry {
  name: string;
  version?: string;
  description?: string;
  status: string;
  tools?: string[];
  skills?: string[];
}

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await axiosInstance.get("/kernel/plugins", { baseURL: BASE });
        setPlugins(res?.data?.plugins || (res as any)?.plugins || []);
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
        <Puzzle size={16} className="text-orange-400" />
        <h2 className="text-sm font-semibold text-white">Plugins</h2>
        <span className="text-xs text-slate-500 ml-auto">{plugins.length} installed</span>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
        {plugins.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Puzzle size={28} className="mb-2 opacity-40" />
            <p>No plugins installed</p>
          </div>
        ) : plugins.map((p) => (
          <div key={p.name} className="px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-sm text-white font-medium">{p.name}</span>
              {p.version && <span className="text-[10px] text-slate-500">v{p.version}</span>}
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${p.status === "loaded" ? "bg-green-500/15 text-green-400" : "bg-slate-700/50 text-slate-400"}`}>{p.status}</span>
            </div>
            {p.description && <p className="text-[11px] text-slate-500 mt-1">{p.description}</p>}
            {p.tools && p.tools.length > 0 && (
              <p className="text-[10px] text-slate-600 mt-1">Tools: {p.tools.join(", ")}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
