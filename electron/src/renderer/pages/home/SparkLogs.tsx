import { BarChart2, MessageSquare, Wrench, Calendar, Flame } from "lucide-react";
import { useMemo } from "react";
import { loadSessions, threadStorageKey } from "@/hooks/useSessionManager";

interface DayData { queries: number; tools: number }

function buildActivityMap(): Record<string, DayData> {
  const sessions = loadSessions();
  const map: Record<string, DayData> = {};
  for (const session of sessions) {
    try {
      const raw = localStorage.getItem(threadStorageKey(session.id));
      if (!raw) continue;
      const threads: { timestamp?: string; tools?: unknown[] }[] = JSON.parse(raw);
      for (const t of threads) {
        if (!t.timestamp) continue;
        const day = t.timestamp.slice(0, 10);
        if (!map[day]) map[day] = { queries: 0, tools: 0 };
        map[day].queries++;
        map[day].tools += t.tools?.length ?? 0;
      }
    } catch { /* corrupt data — skip */ }
  }
  return map;
}

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function heatColor(count: number, max: number): string {
  if (count === 0) return "rgba(255,255,255,0.04)";
  const intensity = Math.min(count / max, 1);
  if (intensity < 0.25) return "rgba(217,119,87,0.25)";
  if (intensity < 0.5)  return "rgba(217,119,87,0.45)";
  if (intensity < 0.75) return "rgba(217,119,87,0.65)";
  return "rgba(217,119,87,0.90)";
}

export default function SparkLogs() {
  const dayMap = useMemo(() => buildActivityMap(), []);

  // ── Stats ──────────────────────────────────────────────────────────────
  const totalQueries = useMemo(() => Object.values(dayMap).reduce((s, d) => s + d.queries, 0), [dayMap]);
  const totalTools   = useMemo(() => Object.values(dayMap).reduce((s, d) => s + d.tools,   0), [dayMap]);
  const activeDays   = useMemo(() => Object.keys(dayMap).length, [dayMap]);
  const avgPerDay    = activeDays > 0 ? (totalQueries / activeDays).toFixed(1) : "0";
  const streak = useMemo(() => {
    let s = 0;
    const today = new Date();
    for (let i = 0; i < 365; i++) {
      const d = new Date(today); d.setDate(today.getDate() - i);
      if (!dayMap[isoDate(d)]) break;
      s++;
    }
    return s;
  }, [dayMap]);

  // ── 14-day bar chart ───────────────────────────────────────────────────
  const last14 = useMemo(() => {
    const out = [];
    for (let i = 13; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      const key = isoDate(d);
      out.push({
        key,
        short: d.toLocaleDateString("en-US", { weekday: "short" }),
        date:  d.getDate(),
        month: d.getMonth(),
        isToday: i === 0,
        queries: dayMap[key]?.queries ?? 0,
        tools:   dayMap[key]?.tools   ?? 0,
      });
    }
    return out;
  }, [dayMap]);
  const barMax = Math.max(...last14.map(d => d.queries), 1);

  // ── 90-day heatmap (13 weeks) ──────────────────────────────────────────
  const heatmap = useMemo(() => {
    const today = new Date();
    // Align to Sunday of 13 weeks ago
    const start = new Date(today);
    start.setDate(today.getDate() - 90);
    start.setDate(start.getDate() - start.getDay()); // back to Sunday

    const weeks: { key: string; queries: number; label: string }[][] = [];
    for (let w = 0; w < 13; w++) {
      const week = [];
      for (let d = 0; d < 7; d++) {
        const cell = new Date(start);
        cell.setDate(start.getDate() + w * 7 + d);
        const key = isoDate(cell);
        week.push({ key, queries: dayMap[key]?.queries ?? 0, label: cell.toLocaleDateString("en-US", { month: "short", day: "numeric" }) });
      }
      weeks.push(week);
    }
    return weeks;
  }, [dayMap]);

  const heatMax = Math.max(...heatmap.flat().map(c => c.queries), 1);

  // Month labels for heatmap header
  const monthMarkers = useMemo(() => {
    const markers: { week: number; label: string }[] = [];
    let lastMonth = -1;
    heatmap.forEach((week, wi) => {
      const m = new Date(week[0].key).getMonth();
      if (m !== lastMonth) { markers.push({ week: wi, label: MONTH_LABELS[m] }); lastMonth = m; }
    });
    return markers;
  }, [heatmap]);

  const isEmpty = totalQueries === 0;

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
        <BarChart2 size={15} style={{ color: "var(--sp-accent)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>
          Activity
        </h2>
      </div>

      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "24px 28px", display: "flex", flexDirection: "column", gap: 28 }}>

        {isEmpty ? (
          <div style={{
            flex: 1, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 12,
            color: "var(--sp-ink-4)",
          }}>
            <BarChart2 size={32} strokeWidth={1.2} style={{ opacity: 0.3 }} />
            <p className="sp-mono" style={{ fontSize: 13 }}>No conversations yet</p>
            <p className="sp-mono" style={{ fontSize: 11 }}>Chat with Spark to see your activity here</p>
          </div>
        ) : (
          <>
            {/* ── Stats row ── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
              {[
                { icon: MessageSquare, label: "Total queries",  value: totalQueries },
                { icon: Wrench,        label: "Tools run",      value: totalTools   },
                { icon: Calendar,      label: "Active days",    value: activeDays   },
                { icon: Flame,         label: "Day streak",     value: streak       },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} style={{
                  padding: "14px 16px",
                  background: "var(--sp-bg-2)",
                  border: "1px solid var(--sp-line)",
                  borderRadius: 10,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
                    <Icon size={13} style={{ color: "var(--sp-accent)" }} />
                    <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {label}
                    </span>
                  </div>
                  <span style={{ fontSize: 26, fontWeight: 600, color: "var(--sp-ink)", lineHeight: 1 }}>
                    {value}
                  </span>
                  {label === "Active days" && (
                    <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", display: "block", marginTop: 4 }}>
                      avg {avgPerDay}/day
                    </span>
                  )}
                </div>
              ))}
            </div>

            {/* ── 14-day bar chart ── */}
            <div style={{
              background: "var(--sp-bg-2)",
              border: "1px solid var(--sp-line)",
              borderRadius: 12,
              padding: "18px 20px 14px",
            }}>
              <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 16 }}>
                Last 14 days
              </p>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 100 }}>
                {last14.map(day => {
                  const h = barMax > 0 ? Math.max((day.queries / barMax) * 84, day.queries > 0 ? 6 : 0) : 0;
                  return (
                    <div key={day.key} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 5, position: "relative" }} title={`${day.key}: ${day.queries} queries, ${day.tools} tools`}>
                      {day.queries > 0 && (
                        <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", position: "absolute", top: 0, transform: "translateY(-14px)" }}>
                          {day.queries}
                        </span>
                      )}
                      <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end" }}>
                        <div style={{
                          width: "100%",
                          height: h,
                          background: day.isToday
                            ? "var(--sp-accent)"
                            : day.queries > 0 ? "rgba(217,119,87,0.45)" : "rgba(255,255,255,0.04)",
                          borderRadius: "3px 3px 0 0",
                          transition: "height 400ms ease",
                          minHeight: 3,
                        }} />
                      </div>
                    </div>
                  );
                })}
              </div>
              {/* Day labels */}
              <div style={{ display: "flex", gap: 5, marginTop: 6 }}>
                {last14.map(day => (
                  <div key={day.key} style={{ flex: 1, textAlign: "center" }}>
                    <span className="sp-mono" style={{
                      fontSize: 9,
                      color: day.isToday ? "var(--sp-accent)" : "var(--sp-ink-4)",
                      fontWeight: day.isToday ? 600 : 400,
                    }}>
                      {day.isToday ? "today" : day.short}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* ── 90-day heatmap ── */}
            <div style={{
              background: "var(--sp-bg-2)",
              border: "1px solid var(--sp-line)",
              borderRadius: 12,
              padding: "18px 20px",
            }}>
              <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
                90-day overview
              </p>
              <div style={{ display: "flex", gap: 6 }}>
                {/* Day-of-week labels */}
                <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingTop: 18 }}>
                  {DAY_LABELS.map((d, i) => (
                    <div key={d} style={{ height: 12, display: "flex", alignItems: "center" }}>
                      {i % 2 === 1 && (
                        <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)", width: 24, textAlign: "right" }}>
                          {d}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                {/* Grid */}
                <div style={{ flex: 1 }}>
                  {/* Month markers */}
                  <div style={{ display: "flex", marginBottom: 4, position: "relative", height: 14 }}>
                    {monthMarkers.map(({ week, label }) => (
                      <span key={label + week} className="sp-mono" style={{
                        position: "absolute",
                        left: `calc(${(week / 13) * 100}%)`,
                        fontSize: 9, color: "var(--sp-ink-4)",
                      }}>
                        {label}
                      </span>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 3 }}>
                    {heatmap.map((week, wi) => (
                      <div key={wi} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        {week.map(cell => (
                          <div
                            key={cell.key}
                            title={cell.queries > 0 ? `${cell.label}: ${cell.queries} ${cell.queries === 1 ? "query" : "queries"}` : cell.label}
                            style={{
                              width: 12, height: 12,
                              borderRadius: 3,
                              background: heatColor(cell.queries, heatMax),
                              border: "1px solid rgba(255,255,255,0.03)",
                              cursor: cell.queries > 0 ? "default" : "default",
                              transition: "background 200ms",
                            }}
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {/* Legend */}
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 12, justifyContent: "flex-end" }}>
                <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)" }}>Less</span>
                {[0, 0.2, 0.5, 0.8, 1].map(v => (
                  <div key={v} style={{ width: 10, height: 10, borderRadius: 2, background: heatColor(v * heatMax, heatMax) }} />
                ))}
                <span className="sp-mono" style={{ fontSize: 9, color: "var(--sp-ink-4)" }}>More</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
