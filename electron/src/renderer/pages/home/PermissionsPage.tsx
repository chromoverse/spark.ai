import { Shield, X, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useAppSelector } from "@/store/hooks";
import axiosInstance from "@/utils/axiosConfig";

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export default function PermissionsPage() {
  const { user } = useAppSelector((s) => s.auth);
  const [fullAccess, setFullAccess] = useState(false);
  const [commands, setCommands] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPermissions = async () => {
    if (!user?._id) return;
    try {
      const res = await axiosInstance.get(`/kernel/permissions?user_id=${user._id}`, { baseURL: BASE });
      const data = res?.data || res;
      setFullAccess(data.full_access ?? false);
      setCommands(data.allowed_commands ?? []);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchPermissions(); }, [user?._id]);

  const revoke = async (cmd?: string) => {
    if (!user?._id) return;
    const params = cmd ? `user_id=${user._id}&command=${cmd}` : `user_id=${user._id}`;
    await axiosInstance.post(`/kernel/permissions/revoke?${params}`, {}, { baseURL: BASE });
    fetchPermissions();
  };

  if (loading) {
    return <div className="flex items-center justify-center h-full"><div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-4 border-b border-slate-800">
        <Shield size={16} className="text-emerald-400" />
        <h2 className="text-sm font-semibold text-white">Permissions</h2>
        <span className="text-xs text-slate-500 ml-auto">{commands.length} granted</span>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {/* Full access toggle */}
        <div className="px-4 py-3 bg-slate-900/40 border border-slate-800 rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className={fullAccess ? "text-green-400" : "text-slate-500"} />
            <div>
              <span className="text-sm text-white font-medium">Full Shell Access</span>
              <p className="text-[11px] text-slate-500">Bypass all command approval prompts</p>
            </div>
          </div>
          {fullAccess && (
            <button onClick={() => revoke()} className="text-xs px-2 py-1 rounded bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors">
              Revoke
            </button>
          )}
          {!fullAccess && <span className="text-[11px] text-slate-600">Disabled</span>}
        </div>

        {/* Individual commands */}
        {commands.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500 text-sm">
            <Shield size={28} className="mb-2 opacity-40" />
            <p>No individual command permissions granted</p>
            <p className="text-xs mt-1">Spark will ask before running new commands</p>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="text-xs text-slate-500 px-1 mb-2">Allowed Commands</p>
            {commands.map((cmd) => (
              <div key={cmd} className="px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg flex items-center justify-between">
                <span className="text-sm text-white font-mono">{cmd}</span>
                <button onClick={() => revoke(cmd)} className="p-1 rounded hover:bg-red-500/15 text-slate-500 hover:text-red-400 transition-colors">
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
