import {
  Globe, FolderOpen, Mail, Monitor, MapPin, Sparkles,
  Search, FileText, Terminal, Camera, Cloud, Wand2,
  Wrench, Battery, Clipboard, Package, type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getJson } from "@/utils/axiosConfig";

interface ToolEntry {
  name: string;
  description: string;
  category: string;
  execution_target: string;
}

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

// ── Friendly metadata ─────────────────────────────────────────────────────────

const TOOL_META: Record<string, { label: string; description: string; icon: LucideIcon }> = {
  web_research:       { label: "Web Research",      icon: Globe,      description: "Deep research on any topic — finds, reads, and summarises information from multiple sources." },
  web_search:         { label: "Web Search",        icon: Search,     description: "Quick search to find links, facts, and current information from the web." },
  web_scrape:         { label: "Web Scrape",        icon: Globe,      description: "Reads and extracts content from any webpage URL." },
  file_create:        { label: "Create File",       icon: FileText,   description: "Creates new files on your computer with content you specify." },
  file_open:          { label: "Open File",         icon: FolderOpen, description: "Opens a file or folder in the appropriate app on your system." },
  file_read:          { label: "Read File",         icon: FileText,   description: "Reads and returns the contents of a file from your computer." },
  folder_organize:    { label: "Organise Folder",   icon: FolderOpen, description: "Sorts and organises files inside a folder by type, date, or name." },
  email_send:         { label: "Send Email",        icon: Mail,       description: "Composes and sends emails from your connected Gmail account." },
  email_list:         { label: "Read Inbox",        icon: Mail,       description: "Fetches your latest emails so you can ask questions about them." },
  email_read:         { label: "Read Email",        icon: Mail,       description: "Opens and reads a specific email thread in full." },
  message_send:       { label: "Send Message",      icon: Mail,       description: "Sends a message via a connected messaging service." },
  app_open:           { label: "Open App",          icon: Monitor,    description: "Launches any application installed on your computer by name." },
  shell_execute:      { label: "Run Command",       icon: Terminal,   description: "Runs a shell command on your computer and returns the output." },
  shell_agent:        { label: "Shell Agent",       icon: Terminal,   description: "Autonomously completes multi-step tasks in the terminal." },
  screenshot_capture: { label: "Screenshot",        icon: Camera,     description: "Captures your screen or a specific window and saves the image." },
  battery_status:     { label: "Battery Status",    icon: Battery,    description: "Checks your laptop battery level and charging state." },
  clipboard_read:     { label: "Read Clipboard",    icon: Clipboard,  description: "Reads the current contents of your clipboard." },
  current_location:   { label: "My Location",       icon: MapPin,     description: "Detects your current location to power location-aware queries." },
  weather_current:    { label: "Current Weather",   icon: Cloud,      description: "Gets the current weather for your location or any city." },
  weather_forecast:   { label: "Weather Forecast",  icon: Cloud,      description: "Fetches a multi-day weather forecast for any location." },
  ai_summarize:       { label: "Summarise",         icon: Sparkles,   description: "Summarises long text, articles, or documents into key points." },
  content_generate:   { label: "Write Content",     icon: Wand2,      description: "Generates written content — emails, posts, captions, code, and more." },
};

// ── Category groups ────────────────────────────────────────────────────────────

interface CategoryDef {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  color: string;
  bg: string;
  border: string;
  tools: string[];
}

const CATEGORIES: CategoryDef[] = [
  {
    id: "research",
    label: "Search & Research",
    description: "Find information, read pages, and research any topic on the web.",
    icon: Globe,
    color: "#87a7c4",
    bg: "rgba(135,167,196,0.08)",
    border: "rgba(135,167,196,0.18)",
    tools: ["web_research", "web_search", "web_scrape"],
  },
  {
    id: "ai",
    label: "AI & Writing",
    description: "Let Spark read, summarise, or write content for you.",
    icon: Sparkles,
    color: "var(--sp-accent)",
    bg: "var(--sp-accent-soft)",
    border: "rgba(217,119,87,0.18)",
    tools: ["ai_summarize", "content_generate"],
  },
  {
    id: "email",
    label: "Email & Messaging",
    description: "Manage your inbox and send messages without leaving Spark.",
    icon: Mail,
    color: "#c97164",
    bg: "rgba(201,112,100,0.08)",
    border: "rgba(201,112,100,0.18)",
    tools: ["email_list", "email_read", "email_send", "message_send"],
  },
  {
    id: "files",
    label: "Files & Folders",
    description: "Create, read, open, and organise files on your computer.",
    icon: FolderOpen,
    color: "#d4a04a",
    bg: "rgba(212,160,74,0.08)",
    border: "rgba(212,160,74,0.18)",
    tools: ["file_create", "file_read", "file_open", "folder_organize"],
  },
  {
    id: "system",
    label: "Apps & System",
    description: "Control your computer — open apps, run commands, take screenshots.",
    icon: Monitor,
    color: "#a78bfa",
    bg: "rgba(167,139,250,0.08)",
    border: "rgba(167,139,250,0.18)",
    tools: ["app_open", "shell_execute", "shell_agent", "screenshot_capture", "battery_status", "clipboard_read"],
  },
  {
    id: "location",
    label: "Location & Weather",
    description: "Get your location and real-time weather anywhere in the world.",
    icon: MapPin,
    color: "#7fb685",
    bg: "rgba(127,182,133,0.08)",
    border: "rgba(127,182,133,0.18)",
    tools: ["current_location", "weather_current", "weather_forecast"],
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await getJson<{ data?: { tools?: ToolEntry[] }; tools?: ToolEntry[] }>("/kernel/tools", { baseURL: BASE });
        setTools(res?.data?.tools || res?.tools || []);
      } catch { /* silent — fall back to static metadata */ }
      finally { setLoading(false); }
    })();
  }, []);

  const registeredNames = new Set(tools.map(t => t.name));

  // Tools present on server but not in any category (unknown/plugin tools)
  const knownToolNames = new Set(CATEGORIES.flatMap(c => c.tools));
  const extraTools = tools.filter(t => !knownToolNames.has(t.name));

  return (
    <div style={{
      height: "100%", display: "flex", flexDirection: "column",
      background: "var(--sp-bg)",
      fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
    }}>
      {/* ── Header ── */}
      <div style={{
        padding: "14px 28px 12px",
        borderBottom: "1px solid var(--sp-line)",
        display: "flex", alignItems: "center", gap: 10,
        flexShrink: 0,
      }}>
        <Sparkles size={15} style={{ color: "var(--sp-accent)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>
          Capabilities
        </h2>
        {!loading && tools.length > 0 && (
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", marginLeft: 4 }}>
            {tools.length} tools available
          </span>
        )}
      </div>

      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "32px 28px 40px" }}>
        <div style={{ maxWidth: 780, margin: "0 auto" }}>

          {/* ── Intro ── */}
          <div style={{ marginBottom: 36, textAlign: "center" }}>
            <h1 className="sp-serif" style={{ margin: "0 0 10px", fontSize: 26, color: "var(--sp-ink)", fontWeight: 400, letterSpacing: "-0.01em" }}>
              What can Spark do?
            </h1>
            <p style={{ fontSize: 14, color: "var(--sp-ink-3)", lineHeight: 1.65, maxWidth: 480, margin: "0 auto" }}>
              Just ask naturally — Spark figures out which tools to use and chains them together to get things done.
            </p>
          </div>

          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", paddingTop: 60 }}>
              <div style={{ width: 18, height: 18, border: "2px solid var(--sp-line-2)", borderTopColor: "var(--sp-accent)", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
              {CATEGORIES.map(cat => {
                const catTools = cat.tools
                  .filter(name => {
                    // Show if server confirms it exists, or if no server data yet
                    if (tools.length === 0) return true;
                    return registeredNames.has(name);
                  });
                if (catTools.length === 0) return null;

                const CatIcon = cat.icon;
                return (
                  <div key={cat.id}>
                    {/* Category header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                        background: cat.bg,
                        border: `1px solid ${cat.border}`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        <CatIcon size={15} style={{ color: cat.color }} />
                      </div>
                      <div>
                        <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>
                          {cat.label}
                        </p>
                        <p style={{ margin: 0, fontSize: 12, color: "var(--sp-ink-4)", marginTop: 1 }}>
                          {cat.description}
                        </p>
                      </div>
                    </div>

                    {/* Tool cards grid */}
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                      gap: 10,
                      paddingLeft: 42,
                    }}>
                      {catTools.map(name => {
                        const meta = TOOL_META[name];
                        const serverTool = tools.find(t => t.name === name);
                        const label = meta?.label ?? name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                        const desc = meta?.description ?? serverTool?.description ?? "";
                        const ToolIcon = meta?.icon ?? Wrench;
                        return (
                          <div key={name} style={{
                            padding: "12px 14px",
                            background: "var(--sp-bg-2)",
                            border: "1px solid var(--sp-line)",
                            borderRadius: 9,
                            display: "flex", gap: 10, alignItems: "flex-start",
                          }}>
                            <div style={{
                              width: 28, height: 28, borderRadius: 6, flexShrink: 0,
                              background: cat.bg,
                              border: `1px solid ${cat.border}`,
                              display: "flex", alignItems: "center", justifyContent: "center",
                            }}>
                              <ToolIcon size={13} style={{ color: cat.color }} />
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--sp-ink)" }}>
                                {label}
                              </p>
                              {desc && (
                                <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--sp-ink-3)", lineHeight: 1.55 }}>
                                  {desc}
                                </p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              {/* ── Uncategorised / plugin tools ── */}
              {extraTools.length > 0 && (
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                      background: "rgba(255,255,255,0.04)",
                      border: "1px solid var(--sp-line)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <Package size={15} style={{ color: "var(--sp-ink-3)" }} />
                    </div>
                    <div>
                      <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>Other</p>
                      <p style={{ margin: 0, fontSize: 12, color: "var(--sp-ink-4)", marginTop: 1 }}>Additional tools loaded from plugins.</p>
                    </div>
                  </div>
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                    gap: 10,
                    paddingLeft: 42,
                  }}>
                    {extraTools.map(t => (
                      <div key={t.name} style={{
                        padding: "12px 14px",
                        background: "var(--sp-bg-2)",
                        border: "1px solid var(--sp-line)",
                        borderRadius: 9,
                        display: "flex", gap: 10, alignItems: "flex-start",
                      }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: 6, flexShrink: 0,
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid var(--sp-line)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                        }}>
                          <Wrench size={12} style={{ color: "var(--sp-ink-3)" }} />
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--sp-ink)" }}>
                            {t.name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                          </p>
                          {t.description && (
                            <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--sp-ink-3)", lineHeight: 1.55 }}>
                              {t.description}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
