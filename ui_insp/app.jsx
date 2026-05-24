// Main app — left nav, activity timeline, command input.

const { useState: useState_App, useEffect: useEffect_App, useRef: useRef_App } = React;

/* =========================================================
   LOCAL SERVICE RESULT CARD — hospital list redesign
   ========================================================= */
const LocalServiceCard = ({ result }) => {
  const [focused, setFocused] = useState_App(0);
  const main = result.items[focused];
  return (
    <div style={{
      marginTop: 12,
      border: "1px solid var(--line)",
      borderRadius: 10,
      background: "var(--bg-2)",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 14px",
        borderBottom: "1px solid var(--line)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "var(--ink-3)", display: "flex" }}>
            <Icon name="pin" size={14}/>
          </span>
          <span style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>{result.title}</span>
          <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>· {result.count} found near Kathmandu</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="mono" style={pillBtnGhostXs}>Map</button>
          <button className="mono" style={pillBtnGhostXs}>List</button>
          <button className="mono" style={pillBtnGhostXs}><Icon name="x" size={11}/></button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 0 }}>
        {/* Featured panel */}
        <div style={{
          padding: 16,
          borderRight: "1px solid var(--line)",
          background: tonePanelBg(main.tone),
          position: "relative",
          minHeight: 280,
          display: "flex",
          flexDirection: "column",
        }}>
          <ToneIllustration tone={main.tone}/>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 8, marginTop: 8, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <RankBadge rank={main.rank}/>
              <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>{main.type}</span>
            </div>
            <h3 className="serif" style={{
              margin: 0,
              fontSize: 30,
              lineHeight: 1.05,
              color: "var(--ink)",
              fontWeight: 400,
              letterSpacing: "-0.01em",
            }}>{main.name}</h3>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 2, color: "var(--ink-2)", fontSize: 12 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <Icon name="star" size={12} style={{ color: "var(--warn)" }}/>
                <span style={{ color: "var(--ink)", fontWeight: 500 }}>{main.rating}</span>
                <span className="mono" style={{ color: "var(--ink-4)" }}>({main.reviews.toLocaleString()})</span>
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: 99,
                  background: main.open ? "var(--ok)" : "var(--err)",
                }}/>
                <span className="mono" style={{ color: "var(--ink-2)" }}>{main.open ? "Open" : "Closed"} · {main.hours}</span>
              </span>
              <span className="mono" style={{ color: "var(--ink-3)" }}>{main.distance}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
              <Icon name="pin" size={12} style={{ color: "var(--ink-3)" }}/>
              {main.address}
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {main.specialties.map(s => (
                <span key={s} className="mono" style={{
                  fontSize: 10,
                  padding: "2px 7px",
                  borderRadius: 99,
                  border: "1px solid var(--line-2)",
                  color: "var(--ink-2)",
                  background: "rgba(0,0,0,0.15)",
                }}>{s}</span>
              ))}
            </div>

            <div style={{ flex: 1 }}/>

            <div style={{ display: "flex", gap: 8 }}>
              <button style={primaryBtn}>
                <Icon name="pin" size={12}/> Get directions
              </button>
              <button style={secondaryBtn}>
                <Icon name="phone" size={12}/> Call
              </button>
              <button style={ghostBtn}>
                <Icon name="external" size={12}/>
              </button>
            </div>
          </div>
        </div>

        {/* List */}
        <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {result.items.map((it, i) => (
            <button
              key={it.rank}
              onClick={() => setFocused(i)}
              style={{
                textAlign: "left",
                padding: "10px 10px",
                borderRadius: 8,
                border: "1px solid " + (i === focused ? "var(--line-2)" : "transparent"),
                background: i === focused ? "var(--bg-3)" : "transparent",
                color: "var(--ink)",
                cursor: "pointer",
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
              }}
            >
              <RankBadge rank={it.rank} small/>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{it.name}</span>
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)", marginLeft: "auto" }}>{it.distance}</span>
                </div>
                <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {it.address}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4, fontSize: 11, color: "var(--ink-3)" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                    <Icon name="star" size={10} style={{ color: "var(--warn)" }}/>
                    <span style={{ color: "var(--ink-2)" }}>{it.rating}</span>
                  </span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                    <span style={{ width: 5, height: 5, borderRadius: 99, background: it.open ? "var(--ok)" : "var(--err)" }}/>
                    <span>{it.open ? "Open 24h" : "Closed"}</span>
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

function tonePanelBg(tone) {
  return {
    warm:  "radial-gradient(circle at 0% 0%, rgba(217,119,87,0.10), transparent 55%), var(--bg-2)",
    cool:  "radial-gradient(circle at 0% 0%, rgba(135,167,196,0.10), transparent 55%), var(--bg-2)",
    mauve: "radial-gradient(circle at 0% 0%, rgba(184,148,214,0.10), transparent 55%), var(--bg-2)",
  }[tone] || "var(--bg-2)";
}

const ToneIllustration = ({ tone }) => {
  const colors = {
    warm:  ["#d97757", "#b8694a", "#7a3b25"],
    cool:  ["#87a7c4", "#5e7f9b", "#3a5773"],
    mauve: ["#b894d6", "#8e69b3", "#5e3f7f"],
  }[tone] || ["#7a7468", "#524d44", "#34312a"];
  // Abstract topo lines — feels mappy without being a fake map.
  return (
    <svg
      width="100%" height="100%"
      viewBox="0 0 400 280"
      preserveAspectRatio="xMidYMid slice"
      style={{ position: "absolute", inset: 0, opacity: 0.55 }}
      aria-hidden
    >
      <defs>
        <linearGradient id={"tg-"+tone} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={colors[0]} stopOpacity="0.35"/>
          <stop offset="1" stopColor={colors[2]} stopOpacity="0"/>
        </linearGradient>
      </defs>
      <rect width="400" height="280" fill={`url(#tg-${tone})`}/>
      {Array.from({ length: 12 }).map((_, i) => (
        <path
          key={i}
          d={`M -20 ${20 + i * 28} Q 100 ${i * 22 + 10}, 220 ${40 + i * 24} T 460 ${30 + i * 26}`}
          stroke={colors[1]}
          strokeOpacity={0.25 - i * 0.012}
          strokeWidth="1"
          fill="none"
        />
      ))}
      {/* pin glyph */}
      <g transform="translate(300,90)" opacity="0.85">
        <circle r="28" fill={colors[0]} opacity="0.18"/>
        <circle r="16" fill={colors[0]} opacity="0.28"/>
        <circle r="6"  fill={colors[0]}/>
      </g>
    </svg>
  );
};

const RankBadge = ({ rank, small }) => (
  <span className="mono" style={{
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    width: small ? 18 : 22, height: small ? 18 : 22,
    borderRadius: 5,
    border: "1px solid var(--line-2)",
    background: "var(--bg-3)",
    color: "var(--ink-2)",
    fontSize: small ? 10 : 11,
    fontWeight: 500,
    flex: "none",
  }}>{rank}</span>
);

const primaryBtn = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "8px 12px",
  borderRadius: 6,
  background: "var(--accent)",
  color: "#1a1208",
  fontSize: 12,
  fontWeight: 600,
  border: 0,
  cursor: "pointer",
  fontFamily: "inherit",
};
const secondaryBtn = {
  ...primaryBtn,
  background: "var(--bg-3)",
  color: "var(--ink)",
  border: "1px solid var(--line-2)",
  fontWeight: 500,
};
const ghostBtn = {
  ...secondaryBtn,
  padding: "8px 10px",
  color: "var(--ink-2)",
};
const pillBtnGhostXs = {
  display: "inline-flex", alignItems: "center", gap: 4,
  padding: "3px 8px",
  borderRadius: 4,
  background: "transparent",
  border: "1px solid var(--line)",
  color: "var(--ink-3)",
  fontSize: 10,
  cursor: "pointer",
};

/* =========================================================
   ASSISTANT TURN
   ========================================================= */
const AssistantTurn = ({ turn }) => {
  return (
    <div style={{ display: "flex", gap: 14, padding: "10px 0" }}>
      <div style={{ width: 28, flex: "none", display: "flex", justifyContent: "center", paddingTop: 2 }}>
        <Spark/>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--accent)", letterSpacing: "0.06em", textTransform: "uppercase" }}>Spark</span>
          <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{turn.time}</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55 }}>
          <ToneTag tone={turn.tone}/>
          {turn.text}
        </div>

        {turn.suggestions && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
            {turn.suggestions.map(s => (
              <button key={s} className="mono" style={pillBtnGhostXs}>
                <Icon name="plus" size={10}/> {s}
              </button>
            ))}
          </div>
        )}

        {turn.tools && (
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {turn.tools.map((t, i) => (
              <ToolCard
                key={i}
                tool={t}
                defaultOpen={t.status === "err" || !!t.preview}
              />
            ))}
          </div>
        )}

        {turn.result && turn.result.kind === "local-service" && (
          <LocalServiceCard result={turn.result}/>
        )}
      </div>
    </div>
  );
};

/* =========================================================
   COMMAND INPUT
   ========================================================= */
const CommandInput = () => {
  const [value, setValue] = useState_App("");
  return (
    <div style={{
      borderTop: "1px solid var(--line)",
      background: "linear-gradient(180deg, transparent, var(--bg) 30%)",
      padding: "18px 28px 24px",
    }}>
      <div style={{
        border: "1px solid var(--line-2)",
        background: "var(--bg-2)",
        borderRadius: 10,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        boxShadow: "0 -1px 0 rgba(255,255,255,0.02), 0 6px 24px rgba(0,0,0,0.3)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "var(--accent)", display: "flex", flex: "none" }}>
            <Icon name="chevron-right" size={14}/>
          </span>
          <input
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder="Ask Spark, or type / to run a command…"
            style={{
              flex: 1,
              background: "transparent", border: 0, outline: "none",
              color: "var(--ink)",
              fontSize: 14,
              fontFamily: "inherit",
            }}
          />
          <span className="mono" style={{
            fontSize: 10, color: "var(--ink-4)",
            border: "1px solid var(--line-2)", borderRadius: 4,
            padding: "1px 6px",
          }}>⌘ K</span>
          <button style={{
            ...primaryBtn,
            background: value ? "var(--accent)" : "var(--bg-3)",
            color: value ? "#1a1208" : "var(--ink-3)",
            border: value ? 0 : "1px solid var(--line-2)",
            padding: "6px 10px",
            transition: "all 140ms",
          }}>
            <Icon name="send" size={12}/>
          </button>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {["Inbox", "File Search", "Location", "Research", "Screenshot", "Shell"].map(c => (
            <button key={c} className="mono" style={chipBtn}>
              <span style={{ color: "var(--ink-4)" }}>/</span>{c.toLowerCase().replace(/\s+/g, "_")}
            </button>
          ))}
        </div>
      </div>
      <div className="mono" style={{
        marginTop: 8,
        fontSize: 10, color: "var(--ink-4)",
        display: "flex", justifyContent: "space-between", gap: 12,
      }}>
        <span>connected · gmail · drive · location</span>
        <span>Spark v2.4 · haiku-4.5</span>
      </div>
    </div>
  );
};

const chipBtn = {
  display: "inline-flex", alignItems: "center", gap: 4,
  padding: "3px 8px",
  borderRadius: 4,
  border: "1px solid var(--line)",
  background: "var(--bg)",
  color: "var(--ink-3)",
  fontSize: 11,
  cursor: "pointer",
};

/* =========================================================
   LEFT NAV
   ========================================================= */
const LeftNav = () => {
  const items = [
    { id: "chat", label: "Chat", icon: "command", active: true, count: 18 },
    { id: "act",  label: "Activity", icon: "activity" },
    { id: "tools",label: "Tools", icon: "terminal" },
    { id: "drive",label: "Drive", icon: "drive" },
    { id: "inbox",label: "Inbox", icon: "mail", count: 20 },
  ];
  return (
    <aside style={{
      width: 220, flex: "none",
      borderRight: "1px solid var(--line)",
      background: "var(--bg)",
      display: "flex",
      flexDirection: "column",
      padding: "18px 14px",
      gap: 18,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "0 4px" }}>
        <div style={{
          width: 26, height: 26, borderRadius: 7,
          background: "linear-gradient(135deg,#d97757,#b54f2c)",
          color: "#fff8f0",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.1)",
        }}>
          <Icon name="sparkle" size={15} strokeWidth={1.7}/>
        </div>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
          <span className="serif" style={{ fontSize: 17, color: "var(--ink)", letterSpacing: "-0.01em" }}>Spark</span>
          <span className="mono" style={{ fontSize: 9, color: "var(--ink-4)", letterSpacing: "0.1em", textTransform: "uppercase" }}>assistant</span>
        </div>
      </div>

      <div>
        <div className="mono" style={navLabel}>Session</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {items.map(it => (
            <button key={it.id} style={{
              ...navItem,
              background: it.active ? "var(--bg-2)" : "transparent",
              color: it.active ? "var(--ink)" : "var(--ink-2)",
              border: it.active ? "1px solid var(--line)" : "1px solid transparent",
            }}>
              <span style={{ color: it.active ? "var(--accent)" : "var(--ink-3)", display: "flex" }}>
                <Icon name={it.icon} size={14}/>
              </span>
              <span style={{ flex: 1, textAlign: "left" }}>{it.label}</span>
              {it.count != null && (
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>{it.count}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="mono" style={navLabel}>Recent</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {[
            "Hospitals near me",
            "Drive · file audit",
            "Gmail · daily digest",
            "Screenshot pipeline",
            "Zikia mythology notes",
          ].map((t, i) => (
            <button key={i} style={{ ...navItem, padding: "5px 8px" }}>
              <span style={{ width: 6, height: 6, borderRadius: 99, background: i === 0 ? "var(--accent)" : "var(--ink-4)", flex: "none" }}/>
              <span style={{ flex: 1, textAlign: "left", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontSize: 12 }}>{t}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1 }}/>

      <div style={{
        border: "1px solid var(--line)",
        borderRadius: 8,
        padding: 10,
        background: "var(--bg-2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 24, height: 24, borderRadius: 99,
            background: "linear-gradient(135deg,#3a342a,#1f1c16)",
            border: "1px solid var(--line-2)",
            color: "var(--user-tint)",
            fontFamily: "'Geist Mono'",
            fontSize: 10,
            fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>A</div>
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.2 }}>
            <div style={{ fontSize: 12, color: "var(--ink)" }}>Aanand</div>
            <div className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>pro · workspace</div>
          </div>
          <span style={{ color: "var(--ink-3)", display: "flex" }}>
            <Icon name="more" size={14}/>
          </span>
        </div>
      </div>
    </aside>
  );
};
const navLabel = {
  fontSize: 9,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--ink-4)",
  padding: "0 6px 6px",
};
const navItem = {
  display: "flex", alignItems: "center", gap: 9,
  padding: "6px 8px",
  borderRadius: 6,
  background: "transparent",
  border: "1px solid transparent",
  color: "var(--ink-2)",
  fontSize: 13,
  fontFamily: "inherit",
  cursor: "pointer",
  width: "100%",
};

/* =========================================================
   SESSION HEADER
   ========================================================= */
const SessionHeader = ({ counts }) => (
  <div style={{
    padding: "20px 28px 14px",
    borderBottom: "1px solid var(--line)",
    display: "flex", alignItems: "center", gap: 14,
    background: "var(--bg)",
    position: "sticky", top: 0, zIndex: 5,
  }}>
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h1 className="serif" style={{
          margin: 0, fontSize: 22, color: "var(--ink)", fontWeight: 400, letterSpacing: "-0.01em",
        }}>Activity</h1>
        <span className="mono" style={{
          fontSize: 10, color: "var(--accent)",
          background: "var(--accent-soft)",
          border: "1px solid rgba(217,119,87,0.18)",
          padding: "2px 7px", borderRadius: 99,
          letterSpacing: "0.04em",
        }}>{counts.active} active</span>
        <span style={{
          width: 6, height: 6, borderRadius: 99,
          background: "var(--ok)", boxShadow: "0 0 0 3px var(--ok-soft)",
        }}/>
        <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>live</span>
      </div>
      <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 4 }}>
        {window.SPARK_DATA.sessionTitle} · {window.SPARK_DATA.sessionContext}
      </div>
    </div>

    <div style={{ display: "flex", gap: 8 }}>
      <CounterPill label="ok"  value={counts.ok}  color="var(--ok)"/>
      <CounterPill label="err" value={counts.err} color="var(--err)"/>
      <CounterPill label="ms"  value={counts.ms}  color="var(--ink-3)"/>
    </div>

    <div style={{ display: "flex", gap: 6 }}>
      <button className="mono" style={pillBtnGhostXs}><Icon name="copy" size={11}/> share</button>
      <button className="mono" style={pillBtnGhostXs}>clear</button>
    </div>
  </div>
);

const CounterPill = ({ label, value, color }) => (
  <div style={{
    border: "1px solid var(--line)",
    background: "var(--bg-2)",
    padding: "5px 10px",
    borderRadius: 6,
    display: "flex", alignItems: "baseline", gap: 6,
  }}>
    <span className="mono" style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>{value}</span>
    <span className="mono" style={{ fontSize: 10, color, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
  </div>
);

/* =========================================================
   APP
   ========================================================= */
const App = () => {
  const data = window.SPARK_DATA;
  const counts = useMemo(() => {
    let ok = 0, err = 0, ms = 0;
    data.activity.forEach(a => {
      if (a.tools) a.tools.forEach(t => {
        if (t.status === "ok") ok++;
        if (t.status === "err") err++;
        const m = parseDuration(t.duration);
        if (m) ms += m;
      });
    });
    return { ok, err, ms: ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`, active: 18 };
  }, [data]);

  return (
    <div style={{
      height: "100vh",
      display: "flex",
      position: "relative",
      zIndex: 1,
    }}>
      <LeftNav/>
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <SessionHeader counts={counts}/>
        <div style={{
          flex: 1,
          overflow: "auto",
          padding: "10px 28px 24px",
        }}>
          <div style={{ maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column" }}>
            {data.activity.map((entry, i) => (
              <React.Fragment key={entry.id}>
                {i > 0 && <Divider/>}
                {entry.kind === "user" ? <UserTurn {...entry}/> : <AssistantTurn turn={entry}/>}
              </React.Fragment>
            ))}
            <div style={{ height: 24 }}/>
          </div>
        </div>
        <CommandInput/>
      </main>
    </div>
  );
};

const Divider = () => (
  <div style={{
    height: 1,
    background: "linear-gradient(90deg, transparent, var(--line) 20%, var(--line) 80%, transparent)",
    margin: "4px 0",
    opacity: 0.7,
  }}/>
);

function parseDuration(s) {
  if (!s) return 0;
  if (s.endsWith("ms")) return parseFloat(s);
  if (s.endsWith("s"))  return parseFloat(s) * 1000;
  return 0;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
