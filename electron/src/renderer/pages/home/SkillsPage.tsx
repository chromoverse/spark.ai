import { Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { getJson } from "@/utils/axiosConfig";

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
        const res = await getJson<{ data?: { skills?: SkillEntry[] }; skills?: SkillEntry[] }>("/kernel/skills", { baseURL: BASE });
        setSkills(res?.data?.skills || res?.skills || []);
      } catch { /* silent */ }
      finally { setLoading(false); }
    })();
  }, []);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Zap size={15} style={{ color: "var(--sp-warn)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Skills</h2>
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: "auto" }}>{skills.length} registered</span>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {loading ? (
          <SpinnerCenter />
        ) : skills.length === 0 ? (
          <EmptyState icon={<Zap size={28} strokeWidth={1.2} />} message="No skills registered" sub="Skills are multi-tool workflows from plugins" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 720 }}>
            {skills.map((s) => (
              <div key={s.name} style={{ padding: "10px 14px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>{s.name}</span>
                  {s.plugin && (
                    <span className="sp-mono" style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "rgba(212,160,74,0.08)", color: "var(--sp-warn)", border: "1px solid rgba(212,160,74,0.18)" }}>{s.plugin}</span>
                  )}
                  {s.steps && <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>{s.steps.length} steps</span>}
                </div>
                {s.description && <p style={{ marginTop: 4, fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.5 }}>{s.description}</p>}
                {s.triggers && s.triggers.length > 0 && (
                  <p className="sp-mono" style={{ marginTop: 3, fontSize: 11, color: "var(--sp-ink-4)" }}>
                    Triggers: {s.triggers.slice(0, 3).join(", ")}
                  </p>
                )}
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

function EmptyState({ icon, message, sub }: { icon: React.ReactNode; message: string; sub?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
      <span style={{ opacity: 0.35 }}>{icon}</span>
      <p className="sp-mono" style={{ fontSize: 13 }}>{message}</p>
      {sub && <p className="sp-mono" style={{ fontSize: 11 }}>{sub}</p>}
    </div>
  );
}
