import {
  Activity, Clock, Settings, Globe, Bot, CalendarDays,
  Shield, MessageSquare, MoreHorizontal, Sparkles,
  PanelLeftClose, PanelLeftOpen, ChevronDown, Plus, Trash2, Pin, PinOff,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useAppSelector } from "@/store/hooks";
import {
  loadSessions, deleteSession, pinSession, getActiveSessionId,
  type SessionMeta,
} from "@/hooks/useSessionManager";

export type SidebarItem =
  | "home" | "history" | "spark-logs" | "tools" | "plugins"
  | "skills" | "permissions" | "settings" | "connectors" | "automation" | "bookings";

interface SidebarProps {
  active: SidebarItem;
  onChange: (item: SidebarItem) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

type NavItem = { id: SidebarItem; label: string; icon: React.ComponentType<{ size?: number }> };
type NavGroup = { id: string; label: string; items: NavItem[] };

const topItems: NavItem[] = [
  { id: "home",       label: "Chat",     icon: MessageSquare },
  { id: "spark-logs", label: "Activity", icon: Activity },
  { id: "history",    label: "History",  icon: Clock },
];

const navGroups: NavGroup[] = [
  {
    id: "connect",
    label: "Connect",
    items: [
      { id: "connectors",  label: "Connectors", icon: Globe },
      { id: "automation",  label: "Automation", icon: Bot },
      { id: "bookings",    label: "Bookings",   icon: CalendarDays },
    ],
  },
  {
    id: "system",
    label: "System",
    items: [
      { id: "tools",       label: "Capabilities", icon: Sparkles },
      { id: "permissions", label: "Permissions",  icon: Shield },
      { id: "settings",    label: "Settings",     icon: Settings },
    ],
  },
];

const allFlatItems: NavItem[] = [...topItems, ...navGroups.flatMap(g => g.items)];

function NavBtn({ item, isActive, onClick, collapsed }: {
  item: NavItem; isActive: boolean; onClick: () => void; collapsed?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? item.label : undefined}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: collapsed ? "center" : "flex-start",
        gap: collapsed ? 0 : 10,
        padding: collapsed ? "9px" : "8px 10px",
        borderRadius: 7,
        border: `1px solid ${isActive ? "var(--sp-line-2)" : "transparent"}`,
        background: isActive ? "var(--sp-bg-2)" : "transparent",
        color: isActive ? "var(--sp-ink)" : "var(--sp-ink-2)",
        fontSize: 14,
        cursor: "pointer",
        width: "100%",
        textAlign: "left",
        transition: "background 120ms, color 120ms",
      }}
      onMouseEnter={(e) => {
        if (!isActive) {
          (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-2)";
          (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink)";
        }
      }}
      onMouseLeave={(e) => {
        if (!isActive) {
          (e.currentTarget as HTMLButtonElement).style.background = "transparent";
          (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)";
        }
      }}
    >
      <span style={{ color: isActive ? "var(--sp-accent)" : "var(--sp-ink-3)", display: "flex", flexShrink: 0 }}>
        <item.icon size={16} />
      </span>
      {!collapsed && (
        <>
          <span style={{ flex: 1, fontWeight: isActive ? 500 : 400 }}>{item.label}</span>
          {isActive && (
            <span style={{
              width: 5, height: 5, borderRadius: 99, flexShrink: 0,
              background: "var(--sp-accent)",
              boxShadow: "0 0 0 3px var(--sp-accent-soft)",
            }} />
          )}
        </>
      )}
    </button>
  );
}

// ── Session row with 3-dot menu (portal dropdown) ────────────────────────────

const MENU_HEIGHT = 76; // approximate height of the 2-item dropdown

function SessionRow({
  session, isActive, onSelect, onDelete, onPin,
}: {
  session: SessionMeta;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onPin: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuCoords, setMenuCoords] = useState<{ top?: number; bottom?: number; right: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const openMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (menuOpen) { setMenuOpen(false); return; }
    const rect = btnRef.current!.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const right = window.innerWidth - rect.right + 2;
    if (spaceBelow >= MENU_HEIGHT + 8) {
      setMenuCoords({ top: rect.bottom + 4, right });
    } else {
      setMenuCoords({ bottom: window.innerHeight - rect.top + 4, right });
    }
    setMenuOpen(true);
  };

  const title = session.title || session.preview || "New Session";

  return (
    <div
      style={{ position: "relative" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); }}
    >
      <button
        onClick={onSelect}
        style={{
          display: "flex", alignItems: "center", gap: 9,
          padding: "7px 10px", width: "100%", textAlign: "left",
          borderRadius: 7,
          border: isActive ? "1px solid var(--sp-line-2)" : "1px solid transparent",
          background: isActive ? "var(--sp-bg-2)" : "transparent",
          cursor: "pointer",
          transition: "background 120ms",
        }}
        onMouseEnter={(e) => {
          if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-2)";
        }}
        onMouseLeave={(e) => {
          if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "transparent";
        }}
      >
        {session.pinned && (
          <Pin size={10} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
        )}
        <span style={{
          width: 6, height: 6, borderRadius: 99, flexShrink: 0,
          background: isActive ? "var(--sp-accent)" : "var(--sp-ink-4)",
          boxShadow: isActive ? "0 0 0 2px var(--sp-accent-soft)" : "none",
        }} />
        <span style={{
          flex: 1, fontSize: 12,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          color: isActive ? "var(--sp-ink)" : "var(--sp-ink-3)",
          fontWeight: isActive ? 500 : 400,
        }}>
          {title}
        </span>
        {session.threadCount > 0 && (
          <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", flexShrink: 0 }}>
            {session.threadCount}
          </span>
        )}
      </button>

      {/* 3-dot button — visible on hover */}
      {(hovered || menuOpen) && (
        <button
          ref={btnRef}
          onClick={openMenu}
          style={{
            position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
            width: 22, height: 22, borderRadius: 5,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: menuOpen ? "var(--sp-bg-3)" : "var(--sp-bg-2)",
            border: "1px solid var(--sp-line)",
            color: "var(--sp-ink-3)", cursor: "pointer",
          }}
        >
          <MoreHorizontal size={12} />
        </button>
      )}

      {/* Dropdown — rendered in a portal so it's never clipped by overflow:hidden/auto */}
      {menuOpen && menuCoords && createPortal(
        <div
          ref={menuRef}
          style={{
            position: "fixed",
            top: menuCoords.top,
            bottom: menuCoords.bottom,
            right: menuCoords.right,
            zIndex: 9999,
            background: "var(--sp-bg-2)",
            border: "1px solid var(--sp-line-2)",
            borderRadius: 8,
            padding: 4,
            minWidth: 130,
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
            fontFamily: "'Geist', -apple-system, sans-serif",
          }}
        >
          <button
            onClick={(e) => { e.stopPropagation(); onPin(); setMenuOpen(false); }}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              width: "100%", padding: "7px 10px", borderRadius: 5,
              background: "transparent", border: 0, color: "var(--sp-ink-2)",
              fontSize: 12, cursor: "pointer", textAlign: "left",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-3)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
          >
            {session.pinned ? <PinOff size={12} /> : <Pin size={12} />}
            {session.pinned ? "Unpin" : "Pin"}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); setMenuOpen(false); }}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              width: "100%", padding: "7px 10px", borderRadius: 5,
              background: "transparent", border: 0, color: "var(--sp-err)",
              fontSize: 12, cursor: "pointer", textAlign: "left",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-3)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
          >
            <Trash2 size={12} />
            Delete
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}

// ── Main Sidebar ─────────────────────────────────────────────────────────────

export default function Sidebar({ active, onChange, collapsed = false, onToggleCollapse }: SidebarProps) {
  const { user } = useAppSelector((s) => s.auth);
  const [sessions, setSessions] = useState<SessionMeta[]>(loadSessions);
  const [activeSessionId, setActiveSessionId] = useState(getActiveSessionId);

  // Refresh sessions list when tab changes or periodically
  const refreshSessions = useCallback(() => {
    setSessions(loadSessions());
    setActiveSessionId(getActiveSessionId());
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [active, refreshSessions]);

  // Listen for session changes from HomeLive
  useEffect(() => {
    const handler = () => refreshSessions();
    window.addEventListener("spark:switch-session", handler);
    window.addEventListener("spark:new-session", handler);
    return () => {
      window.removeEventListener("spark:switch-session", handler);
      window.removeEventListener("spark:new-session", handler);
    };
  }, [refreshSessions]);

  const handleSessionSelect = useCallback((sessionId: string) => {
    window.dispatchEvent(new CustomEvent("spark:switch-session", { detail: { sessionId } }));
    onChange("home");
    setTimeout(refreshSessions, 100);
  }, [onChange, refreshSessions]);

  const handleNewSession = useCallback(() => {
    window.dispatchEvent(new Event("spark:new-session"));
    onChange("home");
    setTimeout(refreshSessions, 100);
  }, [onChange, refreshSessions]);

  const handleDeleteSession = useCallback((sessionId: string) => {
    const isActive = sessionId === activeSessionId;
    deleteSession(sessionId);
    if (isActive) {
      window.dispatchEvent(new Event("spark:new-session"));
    }
    refreshSessions();
  }, [activeSessionId, refreshSessions]);

  const handlePinSession = useCallback((sessionId: string) => {
    const s = sessions.find(s => s.id === sessionId);
    if (s) pinSession(sessionId, !s.pinned);
    refreshSessions();
  }, [sessions, refreshSessions]);

  // Sort: pinned first, then by lastActiveAt
  const sortedSessions = useMemo(() => {
    const withThreads = sessions.filter(s => s.threadCount > 0 || s.id === activeSessionId);
    return withThreads.sort((a, b) => {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      return new Date(b.lastActiveAt).getTime() - new Date(a.lastActiveAt).getTime();
    });
  }, [sessions, activeSessionId]);

  // Auto-expand group that contains the active item
  const activeGroupId = navGroups.find(g => g.items.some(i => i.id === active))?.id;
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    () => new Set(activeGroupId ? [activeGroupId] : [])
  );

  useEffect(() => {
    if (activeGroupId) setOpenGroups(new Set([activeGroupId]));
  }, [activeGroupId]);

  // Only one group open at a time
  const toggleGroup = (id: string) => {
    setOpenGroups(prev => prev.has(id) ? new Set() : new Set([id]));
  };

  const userInitial = useMemo(() =>
    (user?.full_name?.[0] || user?.username?.[0] || "U").toUpperCase()
  , [user]);
  const userName = user?.full_name || user?.username || "User";

  return (
    <aside
      style={{
        width: collapsed ? 64 : 256,
        flexShrink: 0,
        height: "100%",
        background: "var(--sp-bg)",
        borderRight: "1px solid var(--sp-line)",
        display: "flex",
        flexDirection: "column",
        padding: collapsed ? "16px 10px" : "16px 12px",
        gap: collapsed ? 12 : 18,
        overflow: "hidden",
        fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
        transition: "width 220ms cubic-bezier(.4,0,.2,1), padding 220ms cubic-bezier(.4,0,.2,1)",
      }}
    >
      {/* ── Logo / Collapse header ─────────────────────────── */}
      {collapsed ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "linear-gradient(135deg, #d97757, #b54f2c)",
            color: "#fff8f0",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.12)",
          }}>
            <Sparkles size={16} strokeWidth={1.7} />
          </div>
          <button
            onClick={onToggleCollapse}
            title="Expand sidebar"
            style={{
              color: "var(--sp-ink-4)", background: "none", border: 0, cursor: "pointer",
              display: "flex", padding: "5px 6px", borderRadius: 6,
              transition: "color 120ms, background 120ms",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink)";
              (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-2)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)";
              (e.currentTarget as HTMLButtonElement).style.background = "none";
            }}
          >
            <PanelLeftOpen size={15} />
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 2px" }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "linear-gradient(135deg, #d97757, #b54f2c)",
            color: "#fff8f0",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.12)",
            flexShrink: 0,
          }}>
            <Sparkles size={16} strokeWidth={1.7} />
          </div>
          <div style={{ flex: 1, lineHeight: 1.2 }}>
            <span className="sp-serif" style={{ fontSize: 20, color: "var(--sp-ink)", letterSpacing: "-0.01em" }}>
              Spark
            </span>
            <span className="sp-mono" style={{ display: "block", fontSize: 9, color: "var(--sp-ink-4)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
              assistant
            </span>
          </div>
          <button
            onClick={onToggleCollapse}
            title="Collapse sidebar"
            style={{
              color: "var(--sp-ink-4)", background: "none", border: 0, cursor: "pointer",
              display: "flex", padding: "5px 6px", borderRadius: 6, flexShrink: 0,
              transition: "color 120ms, background 120ms",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink)";
              (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-2)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)";
              (e.currentTarget as HTMLButtonElement).style.background = "none";
            }}
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      )}

      {/* ── Nav ─────────────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {collapsed ? (
          allFlatItems.map(item => (
            <NavBtn key={item.id} item={item} isActive={active === item.id} onClick={() => onChange(item.id)} collapsed />
          ))
        ) : (
          <>
            {topItems.map(item => (
              <NavBtn key={item.id} item={item} isActive={active === item.id} onClick={() => onChange(item.id)} />
            ))}

            {navGroups.map(group => {
              const isOpen = openGroups.has(group.id);
              const hasActive = group.items.some(i => i.id === active);
              return (
                <div key={group.id} style={{ marginTop: 6 }}>
                  <button
                    onClick={() => toggleGroup(group.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      width: "100%", padding: "5px 10px 5px 8px",
                      background: "none", border: 0, cursor: "pointer",
                      borderRadius: 6,
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--sp-bg-2)"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
                  >
                    <span className="sp-mono" style={{
                      flex: 1, fontSize: 10, color: hasActive ? "var(--sp-accent)" : "var(--sp-ink-4)",
                      letterSpacing: "0.1em", textTransform: "uppercase", textAlign: "left",
                      fontWeight: hasActive ? 600 : 400,
                    }}>
                      {group.label}
                    </span>
                    <span style={{
                      color: "var(--sp-ink-4)",
                      display: "flex",
                      transform: isOpen ? "rotate(0deg)" : "rotate(-90deg)",
                      transition: "transform 180ms ease",
                    }}>
                      <ChevronDown size={12} />
                    </span>
                  </button>

                  {isOpen && (
                    <div style={{ paddingLeft: 8, display: "flex", flexDirection: "column", gap: 1 }}>
                      {group.items.map(item => (
                        <NavBtn key={item.id} item={item} isActive={active === item.id} onClick={() => onChange(item.id)} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* ── Sessions (expanded only) ──────────────────────── */}
      {!collapsed && (
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", padding: "0 8px 6px", gap: 6, flexShrink: 0 }}>
            <p className="sp-mono" style={sectionLabel}>Sessions</p>
            <div style={{ flex: 1 }} />
            <button
              onClick={handleNewSession}
              title="New session"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 20, height: 20, borderRadius: 5,
                background: "transparent", border: "1px solid var(--sp-line)",
                color: "var(--sp-ink-4)", cursor: "pointer",
                transition: "all 120ms",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--sp-line-2)";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--sp-line)";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)";
              }}
            >
              <Plus size={11} />
            </button>
          </div>
          <div className="sp-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 1 }}>
            {sortedSessions.length === 0 ? (
              <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", padding: "4px 10px" }}>
                No sessions yet
              </p>
            ) : (
              sortedSessions.map(s => (
                <SessionRow
                  key={s.id}
                  session={s}
                  isActive={s.id === activeSessionId}
                  onSelect={() => handleSessionSelect(s.id)}
                  onDelete={() => handleDeleteSession(s.id)}
                  onPin={() => handlePinSession(s.id)}
                />
              ))
            )}
          </div>
        </div>
      )}

      {/* ── User profile ─────────────────────────────────────── */}
      {collapsed ? (
        <div style={{ display: "flex", justifyContent: "center" }}>
          <div style={{
            width: 30, height: 30, borderRadius: 99,
            background: "linear-gradient(135deg, #3a342a, #1f1c16)",
            border: "1px solid var(--sp-line-2)",
            color: "var(--sp-user-tint)",
            fontSize: 12, fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "'Geist Mono', ui-monospace, monospace",
          }}>
            {userInitial}
          </div>
        </div>
      ) : (
        <div style={{
          border: "1px solid var(--sp-line)",
          borderRadius: 9,
          padding: "10px 11px",
          background: "var(--sp-bg-2)",
          display: "flex",
          alignItems: "center",
          gap: 9,
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: 99,
            background: "linear-gradient(135deg, #3a342a, #1f1c16)",
            border: "1px solid var(--sp-line-2)",
            color: "var(--sp-user-tint)",
            fontSize: 12, fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
            fontFamily: "'Geist Mono', ui-monospace, monospace",
          }}>
            {userInitial}
          </div>
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.3 }}>
            <div style={{ fontSize: 13, color: "var(--sp-ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 500 }}>
              {userName}
            </div>
            <div className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", marginTop: 1 }}>
              pro
            </div>
          </div>
          <button
            style={{ color: "var(--sp-ink-3)", display: "flex", background: "none", border: 0, cursor: "pointer", padding: 4, borderRadius: 5 }}
            onClick={() => onChange("settings")}
            title="Settings"
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-3)"; }}
          >
            <MoreHorizontal size={15} />
          </button>
        </div>
      )}
    </aside>
  );
}

const sectionLabel: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--sp-ink-4)",
  margin: 0,
};
