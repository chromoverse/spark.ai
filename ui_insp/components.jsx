// Spark — sleek redesign components

const { useState, useMemo } = React;

/* =========================================================
   STATUS DOT
   ========================================================= */
const StatusDot = ({ status = "ok", running = false, size = 6 }) => {
  const color = {
    ok: "var(--ok)",
    err: "var(--err)",
    warn: "var(--warn)",
    info: "var(--info)",
    pending: "var(--ink-3)",
  }[status] || "var(--ink-3)";
  return (
    <span
      style={{
        width: size, height: size, borderRadius: 999,
        background: color,
        display: "inline-block",
        boxShadow: running ? `0 0 0 3px ${color}22` : "none",
        flex: "none",
      }}
    />
  );
};

/* =========================================================
   USER MESSAGE
   ========================================================= */
const UserTurn = ({ time, text }) => (
  <div style={{ display: "flex", gap: 14, padding: "10px 0" }}>
    <div style={{ width: 28, flex: "none", display: "flex", justifyContent: "center", paddingTop: 4 }}>
      <div style={{
        width: 22, height: 22, borderRadius: 6,
        background: "linear-gradient(135deg,#3a342a,#2a2620)",
        border: "1px solid var(--line-2)",
        color: "var(--user-tint)",
        fontFamily: "'Geist Mono'",
        fontSize: 10,
        fontWeight: 600,
        display: "flex", alignItems: "center", justifyContent: "center",
        letterSpacing: "0.04em",
      }}>A</div>
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: "0.06em", textTransform: "uppercase" }}>You</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{time}</span>
      </div>
      <div style={{ marginTop: 4, fontSize: 15, color: "var(--ink)", lineHeight: 1.5 }}>
        {text}
      </div>
    </div>
  </div>
);

/* =========================================================
   ASSISTANT BUBBLE WRAPPER
   ========================================================= */
const Spark = () => (
  <div style={{
    width: 22, height: 22, borderRadius: 6,
    background: "linear-gradient(135deg,#d97757,#b54f2c)",
    color: "#fff8f0",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08), 0 0 0 1px var(--line)",
  }}>
    <Icon name="sparkle" size={13} strokeWidth={1.6}/>
  </div>
);

const ToneTag = ({ tone }) => {
  if (!tone) return null;
  return (
    <span className="mono" style={{
      display: "inline-flex",
      alignItems: "center",
      fontSize: 10,
      padding: "1px 6px",
      borderRadius: 4,
      color: "var(--accent)",
      background: "var(--accent-soft)",
      border: "1px solid rgba(217,119,87,0.18)",
      letterSpacing: "0.02em",
      marginRight: 6,
    }}>{tone}</span>
  );
};

/* =========================================================
   TOOL CARD — collapsible per-tool block
   ========================================================= */
const ToolCard = ({ tool, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);
  const isErr = tool.status === "err";
  const isOk = tool.status === "ok";

  return (
    <div style={{
      border: "1px solid var(--line)",
      borderRadius: 8,
      background: isErr ? "linear-gradient(180deg, rgba(201,112,100,0.04), transparent 60%) , var(--bg-2)" : "var(--bg-2)",
      overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%",
          display: "flex", alignItems: "center", gap: 12,
          padding: "10px 12px",
          background: "transparent",
          border: 0,
          color: "var(--ink)",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span style={{ color: "var(--ink-3)", display: "flex", flex: "none" }}>
          <Icon name={tool.icon} size={14}/>
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
          <span className="mono" style={{ fontSize: 12, color: "var(--ink)", fontWeight: 500 }}>
            {tool.name}
          </span>
          <StatusDot status={tool.status}/>
        </div>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-4)", flex: "none" }}>
          {tool.duration}
        </span>
        <span style={{
          flex: 1, minWidth: 0,
          fontSize: 13,
          color: isErr ? "var(--err)" : "var(--ink-2)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {isErr ? tool.error || tool.summary : tool.summary}
        </span>
        <span style={{
          color: "var(--ink-4)",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
          transition: "transform 160ms ease",
          display: "flex",
        }}>
          <Icon name="chevron-right" size={14}/>
        </span>
      </button>

      {open && (
        <div style={{ borderTop: "1px solid var(--line)", padding: "10px 12px 12px 38px" }}>
          {/* steps */}
          {tool.steps && tool.steps.length > 0 && (
            <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", display: "flex", flexDirection: "column", gap: 4 }}>
              {tool.steps.map((s, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--ink-4)" }}>›</span>
                  <span>{s}</span>
                </div>
              ))}
            </div>
          )}

          {tool.note && (
            <div className="mono" style={{
              marginTop: 8, fontSize: 11, color: "var(--warn)",
              display: "flex", alignItems: "center", gap: 6,
            }}>
              <Icon name="refresh" size={11}/> {tool.note}
            </div>
          )}

          {tool.preview && <ToolPreview preview={tool.preview}/>}

          {isErr && (
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button className="mono" style={pillBtn}>
                <Icon name="refresh" size={11}/> Retry
              </button>
              <button className="mono" style={pillBtnGhost}>View logs</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const pillBtn = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "5px 10px",
  borderRadius: 6,
  border: "1px solid var(--line-2)",
  background: "var(--bg-3)",
  color: "var(--ink-2)",
  fontSize: 11,
  cursor: "pointer",
};
const pillBtnGhost = { ...pillBtn, background: "transparent" };

/* =========================================================
   TOOL PREVIEW — inline list of emails/files
   ========================================================= */
const ToolPreview = ({ preview }) => {
  if (preview.kind === "emails") {
    return (
      <div style={{ marginTop: 10, border: "1px solid var(--line)", borderRadius: 6, overflow: "hidden" }}>
        {preview.items.map((e, i) => (
          <div key={i} style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr auto auto",
            gap: 10,
            padding: "8px 10px",
            borderBottom: i < preview.items.length - 1 ? "1px solid var(--line)" : 0,
            alignItems: "center",
            fontSize: 12,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: 99,
              background: flagColor(e.flag),
            }}/>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <span style={{ fontWeight: 500 }}>{e.from}</span>
                <span style={{ color: "var(--ink-3)" }}> · {e.subject}</span>
              </div>
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{e.time}</span>
            <span style={{ color: "var(--ink-4)" }}><Icon name="external" size={12}/></span>
          </div>
        ))}
        {preview.more && (
          <div className="mono" style={{
            padding: "8px 10px",
            fontSize: 11,
            color: "var(--ink-3)",
            background: "var(--bg-3)",
            borderTop: "1px solid var(--line)",
          }}>
            + {preview.more} more in inbox
          </div>
        )}
      </div>
    );
  }
  if (preview.kind === "files") {
    return (
      <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
        {preview.items.map((f, i) => (
          <div key={i} style={{
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: "8px 10px",
            display: "flex", alignItems: "center", gap: 8,
            background: "var(--bg)",
          }}>
            <span style={{ color: fileColor(f.name), display: "flex" }}>
              <Icon name="file" size={14}/>
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12, color: "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {f.name}
              </div>
              <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>
                {f.size} · {f.time}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

function flagColor(flag) {
  return {
    promo: "#d4a04a",
    build: "#7fb685",
    code: "#87a7c4",
    task: "#b894d6",
  }[flag] || "var(--ink-4)";
}
function fileColor(name) {
  const ext = name.split(".").pop().toLowerCase();
  return {
    docx: "#7aa6d4",
    doc:  "#7aa6d4",
    pdf:  "#d97757",
    xlsx: "#7fb685",
    pptx: "#d4a04a",
  }[ext] || "var(--ink-3)";
}

window.StatusDot = StatusDot;
window.UserTurn = UserTurn;
window.Spark = Spark;
window.ToneTag = ToneTag;
window.ToolCard = ToolCard;
window.ToolPreview = ToolPreview;
