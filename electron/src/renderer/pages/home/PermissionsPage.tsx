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

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Shield size={15} style={{ color: "var(--sp-ok)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Permissions</h2>
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: "auto" }}>{commands.length} granted</span>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {loading ? (
          <SpinnerCenter />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 640 }}>
            {/* Full access toggle */}
            <div style={{ padding: "12px 14px", background: "var(--sp-bg-2)", border: `1px solid ${fullAccess ? "rgba(127,182,133,0.25)" : "var(--sp-line)"}`, borderRadius: 8, display: "flex", alignItems: "center", gap: 10 }}>
              <ShieldCheck size={16} style={{ color: fullAccess ? "var(--sp-ok)" : "var(--sp-ink-4)", flexShrink: 0 }} />
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>Full Shell Access</span>
                <p className="sp-mono" style={{ margin: "2px 0 0", fontSize: 11, color: "var(--sp-ink-3)" }}>Bypass all command approval prompts</p>
              </div>
              {fullAccess ? (
                <button
                  onClick={() => revoke()}
                  className="sp-mono"
                  style={{ fontSize: 11, padding: "4px 10px", borderRadius: 5, background: "var(--sp-err-soft)", color: "var(--sp-err)", border: "1px solid rgba(201,112,100,0.20)", cursor: "pointer" }}
                >
                  Revoke
                </button>
              ) : (
                <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>Disabled</span>
              )}
            </div>

            {/* Commands */}
            {commands.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 0", color: "var(--sp-ink-4)", gap: 10 }}>
                <Shield size={28} strokeWidth={1.2} style={{ opacity: 0.3 }} />
                <p className="sp-mono" style={{ fontSize: 13 }}>No individual command permissions granted</p>
                <p className="sp-mono" style={{ fontSize: 11 }}>Spark will ask before running new commands</p>
              </div>
            ) : (
              <div>
                <p className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8, padding: "0 2px" }}>
                  Allowed Commands
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {commands.map((cmd) => (
                    <div key={cmd} style={{ padding: "9px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span className="sp-mono" style={{ fontSize: 13, color: "var(--sp-ink)" }}>{cmd}</span>
                      <button
                        onClick={() => revoke(cmd)}
                        style={{ padding: 4, borderRadius: 4, background: "none", border: 0, cursor: "pointer", color: "var(--sp-ink-4)", display: "flex" }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-err)"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)"; }}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
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
