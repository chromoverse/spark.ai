// Connector definitions + small brand-tinted badge component.

const CONNECTORS = [
  { id: "gmail",    name: "Gmail",          connected: true,  color: "#ea4335", glyph: "M",  fontSize: 11, mono: false },
  { id: "drive",    name: "Drive",          connected: true,  color: "#1faa59", glyph: "△",  fontSize: 13, mono: false },
  { id: "calendar", name: "Calendar",       connected: true,  color: "#3b82f6", glyph: "31", fontSize: 9,  mono: true  },
  { id: "location", name: "Location",       connected: true,  color: "#d97757", glyph: "◉",  fontSize: 12, mono: false },
  { id: "shell",    name: "Shell",          connected: true,  color: "#7fb685", glyph: ">_", fontSize: 9,  mono: true  },
  { id: "research", name: "Research",       connected: true,  color: "#87a7c4", glyph: "Q",  fontSize: 11, mono: false },
  { id: "slack",    name: "Slack",          connected: false, color: "#b894d6", glyph: "S",  fontSize: 11, mono: false },
  { id: "notion",   name: "Notion",         connected: false, color: "#ece6da", glyph: "N",  fontSize: 11, mono: false },
  { id: "linear",   name: "Linear",         connected: false, color: "#9eaff0", glyph: "L",  fontSize: 11, mono: false },
];

// Map tool name → connector id, used to thread connector branding through tool cards.
const TOOL_TO_CONNECTOR = {
  "Inbox":       "gmail",
  "File Search": "drive",
  "Screenshot":  "shell",
  "App":         "shell",
  "Shell":       "shell",
  "Location":    "location",
  "Research":    "research",
  "Generate":    null,
};

const ConnectorBadge = ({ id, size = 18, ring = false, dim = false }) => {
  const c = CONNECTORS.find(c => c.id === id);
  if (!c) return null;
  return (
    <span style={{
      width: size, height: size, borderRadius: Math.round(size * 0.28),
      background: dim ? "transparent" : `linear-gradient(135deg, ${c.color}, ${shade(c.color, -0.35)})`,
      color: dim ? c.color : "#fff",
      border: dim ? `1px dashed ${hexA(c.color, 0.35)}` : "1px solid " + hexA(c.color, 0.4),
      boxShadow: ring ? `0 0 0 3px ${hexA(c.color, 0.16)}` : "inset 0 0 0 1px rgba(255,255,255,0.08)",
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      flex: "none",
      fontFamily: c.mono ? "'Geist Mono'" : "'Geist'",
      fontWeight: 700,
      fontSize: c.fontSize * (size / 18),
      letterSpacing: c.glyph.length > 1 ? "-0.04em" : 0,
      lineHeight: 1,
    }}>{c.glyph}</span>
  );
};

function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  r = Math.max(0, Math.min(255, Math.round(r + (amt < 0 ? r * amt : (255 - r) * amt))));
  g = Math.max(0, Math.min(255, Math.round(g + (amt < 0 ? g * amt : (255 - g) * amt))));
  b = Math.max(0, Math.min(255, Math.round(b + (amt < 0 ? b * amt : (255 - b) * amt))));
  return `#${[r,g,b].map(v => v.toString(16).padStart(2,"0")).join("")}`;
}
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
}

window.CONNECTORS = CONNECTORS;
window.TOOL_TO_CONNECTOR = TOOL_TO_CONNECTOR;
window.ConnectorBadge = ConnectorBadge;
window.hexA = hexA;
