import { Zap } from "lucide-react";
import { useEffect, useState } from "react";
import axiosInstance from "@/utils/axiosConfig";

interface SkillEntry {
  name: string;
  description?: string;
  plugin?: string;
  triggers?: string[];
  steps?: { task_id: string; tool: string }[];
}

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await axiosInstance.get("/kernel/skills", { baseURL: BASE });
        setSkills(res?.data?.skills || (res as any)?.skills || []);
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
        <Zap size={16} className="text-yellow-400" />
        <h2 className="text-sm font-semibold text-white">Skills</h2>
        <span className="text-xs text-slate-500 ml-auto">{skills.length} registered</span>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
        {skills.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Zap size={28} className="mb-2 opacity-40" />
            <p>No skills registered</p>
            <p className="text-xs mt-1">Skills are multi-tool workflows from plugins</p>
          </div>
        ) : skills.map((s) => (
          <div key={s.name} className="px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-sm text-white font-medium">{s.name}</span>
              {s.plugin && <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400">{s.plugin}</span>}
              {s.steps && <span className="text-[10px] text-slate-500">{s.steps.length} steps</span>}
            </div>
            {s.description && <p className="text-[11px] text-slate-500 mt-1">{s.description}</p>}
            {s.triggers && s.triggers.length > 0 && (
              <p className="text-[10px] text-slate-600 mt-1">Triggers: {s.triggers.slice(0, 3).join(", ")}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
