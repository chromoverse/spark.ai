import { Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import axiosInstance from "@/utils/axiosConfig";

interface ToolEntry {
  name: string;
  description: string;
  category: string;
  execution_target: string;
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

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Wrench size={15} style={{ color: "var(--sp-accent)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Tools</h2>
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: "auto" }}>{tools.length} registered</span>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {loading ? (
          <SpinnerCenter />
        ) : tools.length === 0 ? (
          <EmptyState icon={<Wrench size={28} strokeWidth={1.2} />} message="No tools registered" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 720 }}>
            {tools.map((t) => (
              <div key={t.name} style={{ padding: "10px 14px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>{t.name}</span>
                  <span className="sp-mono" style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "var(--sp-accent-soft)", color: "var(--sp-accent)", border: "1px solid rgba(217,119,87,0.18)" }}>{t.category}</span>
                  <span className="sp-mono" style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "var(--sp-bg-3)", color: "var(--sp-ink-4)", border: "1px solid var(--sp-line)" }}>{t.execution_target}</span>
                </div>
                {t.description && <p style={{ marginTop: 4, fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.5 }}>{t.description}</p>}
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
      {sub && <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>{sub}</p>}
    </div>
  );
}
