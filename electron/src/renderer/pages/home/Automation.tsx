import { Bot } from "lucide-react";

const automationItems = [
  { title: "WhatsApp",        sub: "Automated messaging and responses" },
  { title: "Email Automation", sub: "Auto-reply and email workflows" },
  { title: "Scheduled Tasks",  sub: "Recurring actions and reminders" },
  { title: "Social Media",     sub: "Cross-platform posting and monitoring" },
];

export default function Automation() {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <Bot size={15} style={{ color: "var(--sp-info)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Automation</h2>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 560 }}>
          {automationItems.map((item) => (
            <div key={item.title} style={{ padding: "12px 16px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 8 }}>
              <p style={{ margin: 0, fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>{item.title}</p>
              <p style={{ margin: "3px 0 0", fontSize: 12, color: "var(--sp-ink-3)" }}>{item.sub}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
