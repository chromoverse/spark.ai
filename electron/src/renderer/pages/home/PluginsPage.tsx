import { Puzzle } from "lucide-react";
import { useEffect, useState } from "react";
import axiosInstance from "@/utils/axiosConfig";

interface PluginEntry {
  name: string;
  version?: string;
  description?: string;
  status: string;
  tools?: string[];
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

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Puzzle size={15} style={{ color: "var(--sp-accent)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Plugins</h2>
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: "auto" }}>{plugins.length} installed</span>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
        {loading ? (
          <SpinnerCenter />
        ) : plugins.length === 0 ? (
          <EmptyState icon={<Puzzle size={28} strokeWidth={1.2} />} message="No plugins installed" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 720 }}>
            {plugins.map((p) => (
              <div key={p.name} style={{ padding: "10px 14px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>{p.name}</span>
                  {p.version && <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>v{p.version}</span>}
                  <span className="sp-mono" style={{
                    fontSize: 10, padding: "2px 7px", borderRadius: 4,
                    background: p.status === "loaded" ? "var(--sp-ok-soft)" : "var(--sp-bg-3)",
                    color: p.status === "loaded" ? "var(--sp-ok)" : "var(--sp-ink-4)",
                    border: `1px solid ${p.status === "loaded" ? "rgba(127,182,133,0.20)" : "var(--sp-line)"}`,
                  }}>
                    {p.status}
                  </span>
                </div>
                {p.description && <p style={{ marginTop: 4, fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.5 }}>{p.description}</p>}
                {p.tools && p.tools.length > 0 && (
                  <p className="sp-mono" style={{ marginTop: 3, fontSize: 11, color: "var(--sp-ink-4)" }}>
                    Tools: {p.tools.join(", ")}
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

function EmptyState({ icon, message }: { icon: React.ReactNode; message: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--sp-ink-4)", gap: 10 }}>
      <span style={{ opacity: 0.35 }}>{icon}</span>
      <p className="sp-mono" style={{ fontSize: 13 }}>{message}</p>
    </div>
  );
}
