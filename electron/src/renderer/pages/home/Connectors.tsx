import { Globe, Loader2, RefreshCw, CheckCircle2, XCircle, ExternalLink, Unplug, Plug, X, AlertTriangle } from "lucide-react";
import { useState, useRef } from "react";
import { toast } from "sonner";
import {
  SiGmail, SiGooglecalendar, SiGoogledrive,
  SiSlack, SiNotion, SiGithub, SiSpotify,
} from "react-icons/si";
import type { IconType } from "react-icons";
import { useAppSelector } from "@/store/hooks";
import { useConnectorStatus, type ConnectorStatus } from "@/hooks/useConnectorStatus";

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

// ── Brand icon + colour map ───────────────────────────────────────────────────

const SERVICE_ICONS: Record<string, IconType> = {
  gmail:           SiGmail,
  google_calendar: SiGooglecalendar,
  google_drive:    SiGoogledrive,
  slack:           SiSlack,
  notion:          SiNotion,
  github:          SiGithub,
  spotify:         SiSpotify,
};

const SERVICE_COLORS: Record<string, string> = {
  gmail:           "bg-red-500/15 text-red-400 border-red-500/30",
  google_calendar: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  google_drive:    "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  slack:           "bg-purple-500/15 text-purple-400 border-purple-500/30",
  notion:          "bg-slate-400/15 text-slate-300 border-slate-400/30",
  github:          "bg-slate-500/15 text-slate-300 border-slate-500/30",
  spotify:         "bg-green-500/15 text-green-400 border-green-500/30",
};

// ── ServiceCard ───────────────────────────────────────────────────────────────

interface ServiceCardProps {
  connector: ConnectorStatus;
  userId: string;
  onPollUntilConnected: (id: string, signal: AbortSignal) => Promise<boolean>;
  onDisconnect: (id: string) => Promise<void>;
}

function ServiceCard({ connector, userId, onPollUntilConnected, onDisconnect }: ServiceCardProps) {
  const [waiting, setWaiting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const colorCls = SERVICE_COLORS[connector.id] ?? "bg-slate-500/15 text-slate-300 border-slate-500/30";
  const BrandIcon = SERVICE_ICONS[connector.id] ?? null;

  const handleConnect = async () => {
    const url = `${BASE}/auth/${connector.id}/connect?user_id=${userId}`;
    try {
      await window.electronApi.openExternalUrl(url);
    } catch {
      window.open(url, "_blank");
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setWaiting(true);
    toast.info(`Waiting for ${connector.display_name} authorization…`);
    const ok = await onPollUntilConnected(connector.id, ac.signal);
    abortRef.current = null;
    setWaiting(false);
    if (ac.signal.aborted) return;
    if (ok) {
      toast.success(`${connector.display_name} connected`);
    } else {
      toast.error(`Timed out waiting for ${connector.display_name}. Try again.`);
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setWaiting(false);
  };

  const confirmDisconnect = async () => {
    setConfirmOpen(false);
    setDisconnecting(true);
    try {
      await onDisconnect(connector.id);
      toast.success(`${connector.display_name} disconnected`);
    } catch {
      toast.error(`Failed to disconnect ${connector.display_name}`);
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <>
    {/* ── Revoke confirmation dialog ── */}
    {confirmOpen && (
      <div style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backdropFilter: "blur(4px)",
      }}
        onClick={(e) => { if (e.target === e.currentTarget) setConfirmOpen(false); }}
      >
        <div style={{
          width: "100%", maxWidth: 400,
          background: "var(--sp-bg-2)",
          border: "1px solid var(--sp-line-2)",
          borderRadius: 14,
          boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
          overflow: "hidden",
          fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
        }}>
          {/* Header */}
          <div style={{ padding: "18px 20px 14px", display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 9, flexShrink: 0,
              background: "rgba(201,112,100,0.1)",
              border: "1px solid rgba(201,112,100,0.2)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <AlertTriangle size={17} style={{ color: "var(--sp-err)" }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--sp-ink)" }}>
                Revoke {connector.display_name} access?
              </p>
              <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--sp-ink-3)", lineHeight: 1.55 }}>
                This will revoke Spark's access to your {connector.display_name} account. You won't be able to manage {connector.display_name} from Spark afterward.
              </p>
            </div>
          </div>
          {/* Footer */}
          <div style={{
            padding: "12px 20px 16px",
            borderTop: "1px solid var(--sp-line)",
            display: "flex", justifyContent: "flex-end", gap: 8,
          }}>
            <button
              onClick={() => setConfirmOpen(false)}
              style={{
                padding: "7px 16px", borderRadius: 7,
                background: "var(--sp-bg-3)",
                border: "1px solid var(--sp-line-2)",
                color: "var(--sp-ink-2)", fontSize: 13, cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              onClick={confirmDisconnect}
              style={{
                padding: "7px 16px", borderRadius: 7,
                background: "rgba(201,112,100,0.12)",
                border: "1px solid rgba(201,112,100,0.30)",
                color: "var(--sp-err)", fontSize: 13, fontWeight: 600, cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 6,
              }}
            >
              <Unplug size={13} />
              Revoke access
            </button>
          </div>
        </div>
      </div>
    )}

    <div style={{
      position: "relative",
      background: "var(--sp-bg-2)",
      border: `1px solid ${connector.connected ? "var(--sp-line-2)" : "var(--sp-line)"}`,
      borderRadius: 10,
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 12,
      transition: "border-color 200ms",
      opacity: connector.connected ? 1 : 0.85,
      fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div className={`w-10 h-10 rounded-lg border flex items-center justify-center shrink-0 ${colorCls}`}
          style={{ width: 40, height: 40, borderRadius: 8, border: "1px solid var(--sp-line-2)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {BrandIcon
            ? <BrandIcon size={20} />
            : <span style={{ fontSize: 11, fontWeight: 700, color: "var(--sp-ink-2)" }}>{connector.display_name.slice(0, 2)}</span>
          }
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>{connector.display_name}</span>
            {connector.connected ? (
              <span className="sp-mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--sp-ok)", background: "var(--sp-ok-soft)", border: "1px solid rgba(127,182,133,0.20)", padding: "1px 7px", borderRadius: 99 }}>
                <span style={{ width: 5, height: 5, borderRadius: 99, background: "var(--sp-ok)" }} className="animate-pulse" />
                Connected
              </span>
            ) : (
              <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)", padding: "1px 7px", borderRadius: 99 }}>
                Not connected
              </span>
            )}
          </div>
          <p style={{ margin: "3px 0 0", fontSize: 12, color: "var(--sp-ink-3)", lineHeight: 1.5 }}>{connector.description}</p>
        </div>
      </div>

      {connector.capabilities.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {connector.capabilities.map((cap) => (
            <span key={cap} className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line)", padding: "2px 6px", borderRadius: 4 }}>
              {cap.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {connector.requires_setup && !connector.connected && (
        <p className="sp-mono" style={{ margin: 0, fontSize: 10, color: "var(--sp-warn)", background: "rgba(212,160,74,0.07)", border: "1px solid rgba(212,160,74,0.18)", borderRadius: 5, padding: "5px 10px" }}>
          Requires a personal access token — set up in your .env
        </p>
      )}

      <div style={{ marginTop: "auto" }}>
        {connector.connected ? (
          <button
            onClick={() => setConfirmOpen(true)}
            disabled={disconnecting}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--sp-ink-3)", background: "none", border: "1px solid var(--sp-line-2)", borderRadius: 6, padding: "5px 12px", cursor: "pointer", transition: "all 140ms" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-err)"; (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(201,112,100,0.30)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-3)"; (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--sp-line-2)"; }}
          >
            {disconnecting ? <Loader2 size={12} className="animate-spin" /> : <Unplug size={12} />}
            {disconnecting ? "Disconnecting…" : "Disconnect"}
          </button>
        ) : waiting ? (
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--sp-info)", background: "var(--sp-info-soft)", border: "1px solid rgba(135,167,196,0.20)", borderRadius: 6, padding: "5px 12px", flex: 1 }}>
              <Loader2 size={12} className="animate-spin" />
              Waiting for authorization…
            </div>
            <button onClick={handleCancel} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--sp-ink-3)", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)", borderRadius: 6, padding: "5px 10px", cursor: "pointer" }}>
              <X size={12} /> Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={handleConnect}
            disabled={connector.requires_setup}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: connector.requires_setup ? "var(--sp-ink-4)" : "#1a1208", background: connector.requires_setup ? "var(--sp-bg-3)" : "var(--sp-accent)", border: "none", borderRadius: 6, padding: "5px 12px", cursor: connector.requires_setup ? "not-allowed" : "pointer" }}
          >
            <Plug size={12} />
            Connect
            {!connector.requires_setup && <ExternalLink size={10} style={{ opacity: 0.7 }} />}
          </button>
        )}
      </div>
    </div>
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Connectors() {
  const { user } = useAppSelector((state) => state.auth);
  const userId = (user as any)?._id as string | undefined;

  const { connectors, loading, error, refetch, pollUntilConnected, disconnect } =
    useConnectorStatus(userId);

  const connectedCount = connectors.filter((c) => c.connected).length;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Globe size={15} style={{ color: "var(--sp-info)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Connectors</h2>
        {!loading && (
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: 4 }}>
            {connectedCount}/{connectors.length} connected
          </span>
        )}
        <button onClick={refetch} title="Refresh" style={{ marginLeft: "auto", color: "var(--sp-ink-4)", background: "none", border: 0, cursor: "pointer", display: "flex" }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)"; }}>
          <RefreshCw size={13} />
        </button>
      </div>

      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 120 }}>
              <div style={{ width: 18, height: 18, border: "2px solid var(--sp-line-2)", borderTopColor: "var(--sp-accent)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
            </div>
          ) : error ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 120, gap: 8 }}>
              <XCircle size={20} style={{ color: "var(--sp-err)" }} />
              <p style={{ fontSize: 13, color: "var(--sp-ink-3)" }}>{error}</p>
              <button onClick={refetch} style={{ fontSize: 12, color: "var(--sp-accent)", background: "none", border: 0, cursor: "pointer" }}>Retry</button>
            </div>
          ) : !userId ? (
            <p className="sp-mono" style={{ fontSize: 13, color: "var(--sp-ink-4)", textAlign: "center", padding: "40px 0" }}>Sign in to manage connected services.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              {connectedCount > 0 && (
                <section>
                  <p className="sp-mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: "var(--sp-ok)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10 }}>
                    <CheckCircle2 size={11} /> Connected ({connectedCount})
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {connectors.filter((c) => c.connected).map((c) => (
                      <ServiceCard key={c.id} connector={c} userId={userId} onPollUntilConnected={pollUntilConnected} onDisconnect={disconnect} />
                    ))}
                  </div>
                </section>
              )}
              {connectors.filter((c) => !c.connected).length > 0 && (
                <section>
                  <p className="sp-mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: "var(--sp-ink-4)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10 }}>
                    <Globe size={11} /> Available ({connectors.filter((c) => !c.connected).length})
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {connectors.filter((c) => !c.connected).map((c) => (
                      <ServiceCard key={c.id} connector={c} userId={userId} onPollUntilConnected={pollUntilConnected} onDisconnect={disconnect} />
                    ))}
                  </div>
                </section>
              )}
              {connectors.length === 0 && (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 120, color: "var(--sp-ink-4)", gap: 10 }}>
                  <Globe size={24} strokeWidth={1.2} style={{ opacity: 0.35 }} />
                  <p className="sp-mono" style={{ fontSize: 13 }}>No connectors available</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
