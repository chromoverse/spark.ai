import { useEffect, useRef, useState } from "react";
import {
  Settings,
  Palette,
  Bell,
  Shield,
  Languages,
  Globe,
  Moon,
  HelpCircle,
  Sparkles,
  ChevronRight,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const MENU_BG    = "var(--sp-bg-2)";
const MENU_LINE  = "var(--sp-line)";
const MENU_INK   = "var(--sp-ink)";
const MENU_INK3  = "var(--sp-ink-3)";
const MENU_INK4  = "var(--sp-ink-4)";
const MENU_HOVER = "rgba(255,255,255,0.05)";

function MenuItem({
  icon: Icon,
  label,
  onClick,
  hasSubmenu,
}: {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  label: string;
  onClick?: () => void;
  hasSubmenu?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        width: "100%", padding: "7px 10px",
        background: "transparent", border: "none", cursor: "pointer",
        color: MENU_INK, fontSize: 13, borderRadius: 6,
        textAlign: "left",
        transition: "background 150ms",
      }}
      onMouseEnter={e => (e.currentTarget.style.background = MENU_HOVER)}
      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
    >
      <Icon size={14} style={{ color: MENU_INK3, flexShrink: 0 }} />
      <span style={{ flex: 1 }}>{label}</span>
      {hasSubmenu && <ChevronRight size={12} style={{ color: MENU_INK4 }} />}
    </button>
  );
}

function Divider() {
  return <div style={{ height: 1, background: MENU_LINE, margin: "4px 0" }} />;
}

export default function SettingsDropdown() {
  const [open, setOpen] = useState(false);
  const [subMenu, setSubMenu] = useState<"appearance" | "language" | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setSubMenu(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const close = () => { setOpen(false); setSubMenu(null); };

  const panelStyle: React.CSSProperties = {
    position: "absolute",
    bottom: "calc(100% + 8px)",
    left: 0,
    width: 210,
    background: MENU_BG,
    border: `1px solid ${MENU_LINE}`,
    borderRadius: 10,
    padding: "6px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
    zIndex: 9999,
    fontFamily: "'Geist', -apple-system, sans-serif",
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={() => { setOpen(o => !o); setSubMenu(null); }}
            style={{
              height: 32, padding: "0 8px",
              background: "transparent", border: "none", cursor: "pointer",
              color: open ? "var(--sp-ink)" : "var(--sp-ink-3)",
              borderRadius: 6,
              display: "flex", alignItems: "center",
              transition: "color 150ms, background 150ms",
            }}
            onMouseEnter={e => (e.currentTarget.style.background = MENU_HOVER)}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
          >
            <Settings size={16} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top"><p>Settings</p></TooltipContent>
      </Tooltip>

      {open && (
        <div style={panelStyle}>
          <div style={{ padding: "4px 10px 6px", color: MENU_INK4, fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Settings
          </div>
          <Divider />

          {subMenu === null && (
            <>
              <MenuItem icon={Palette} label="Appearance" hasSubmenu onClick={() => setSubMenu("appearance")} />
              <MenuItem icon={Languages} label="Language" hasSubmenu onClick={() => setSubMenu("language")} />
              <Divider />
              <MenuItem icon={Bell} label="Notifications" onClick={close} />
              <MenuItem icon={Shield} label="Privacy" onClick={close} />
              <MenuItem icon={Globe} label="Network" onClick={close} />
              <Divider />
              <MenuItem icon={HelpCircle} label="Help & Support" onClick={close} />
            </>
          )}

          {subMenu === "appearance" && (
            <>
              <button
                onClick={() => setSubMenu(null)}
                style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px 8px", background: "transparent", border: "none", cursor: "pointer", color: MENU_INK4, fontSize: 12, width: "100%" }}
              >
                ← Appearance
              </button>
              <MenuItem icon={Moon} label="Dark Mode" onClick={close} />
              <MenuItem icon={Sparkles} label="Light Mode" onClick={close} />
              <Divider />
              <MenuItem icon={Settings} label="System Default" onClick={close} />
            </>
          )}

          {subMenu === "language" && (
            <>
              <button
                onClick={() => setSubMenu(null)}
                style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px 8px", background: "transparent", border: "none", cursor: "pointer", color: MENU_INK4, fontSize: 12, width: "100%" }}
              >
                ← Language
              </button>
              {["English", "Español", "Français", "Deutsch"].map(lang => (
                <MenuItem key={lang} icon={Globe} label={lang} onClick={close} />
              ))}
              <Divider />
              <MenuItem icon={Globe} label="More languages..." onClick={close} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
