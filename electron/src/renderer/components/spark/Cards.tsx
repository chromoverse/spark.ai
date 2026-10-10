import { useState } from "react";
import type { ApprovalView, AskView } from "@/store/features/spark/sparkSlice";

// The approval and question cards, shared by the voice overlay and Home. The first answer from any
// of the user's devices wins; the brain closes the card everywhere (approval/ask.resolved).

const RISK: Record<string, string> = { destructive: "var(--sp-err)", write: "var(--sp-warn)", external: "var(--sp-info)" };

const show = (v: unknown): string => (typeof v === "string" ? v : JSON.stringify(v));

/** `full` lists every input on its own line (Home); compact shows two on one line (overlay). */
export function ApprovalCard({ approval, more = 0, full = false }: { approval: ApprovalView; more?: number; full?: boolean }) {
  const decide = (d: "allow" | "deny" | "always"): void => void window.electronApi.brain.approve(approval.id, d);
  const inputs = Object.entries(approval.inputs);
  const destructive = approval.risk === "destructive";
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.035] p-3" role="alertdialog" aria-label={approval.summary}>
      <div className="flex items-center gap-2">
        <span className="size-1.5 rounded-full" style={{ background: RISK[approval.risk] ?? "var(--sp-ink-3)" }} />
        <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--sp-ink-3)]">Needs your OK</span>
        {full && <span className="sp-mono text-[11px] text-[var(--sp-ink-4)]">{approval.tool}</span>}
        {more > 0 && <span className="ml-auto text-[11px] text-[var(--sp-ink-4)]">+{more} more</span>}
      </div>
      <p className="mt-1.5 text-[14px] leading-snug text-[var(--sp-ink)]">{approval.summary}</p>
      {full ? (
        <dl className="sp-mono mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-black/20 px-3 py-2 text-[11.5px]">
          {inputs.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-[var(--sp-ink-4)]">{k}</dt>
              <dd className="break-all text-[var(--sp-ink-2)]">{show(v)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        inputs.length > 0 && (
          <p className="sp-mono mt-1 truncate text-[11px] text-[var(--sp-ink-3)]">
            {inputs.slice(0, 2).map(([k, v]) => `${k}: ${show(v)}`).join("  ·  ")}
          </p>
        )
      )}
      <div className="mt-3 flex items-center gap-2">
        {/* destructive: Deny takes the focus, so Enter is the safe answer */}
        <button className="sp-btn-ghost px-3" onClick={() => decide("deny")} autoFocus={full && destructive}>
          Deny
        </button>
        {approval.options.includes("always") && (
          <button className="sp-btn-ghost px-3" onClick={() => decide("always")}>
            Always allow
          </button>
        )}
        {full && <span className="ml-auto text-[12px] text-[var(--sp-ink-4)]">or say “yes, do it”</span>}
        <button className={`sp-btn-accent px-4 ${full ? "" : "ml-auto"}`} onClick={() => decide("allow")}>
          Allow
        </button>
      </div>
    </div>
  );
}

export function AskCard({ ask }: { ask: AskView }) {
  const [text, setText] = useState("");
  const answer = (a: string): void => {
    if (a.trim()) void window.electronApi.brain.answer(ask.id, a.trim());
  };
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.035] p-3">
      <p className="text-[14px] leading-snug text-[var(--sp-ink)]">{ask.question}</p>
      {ask.options.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          {ask.options.map((o) => (
            <button key={o} className="sp-btn-ghost px-3" onClick={() => answer(o)}>
              {o}
            </button>
          ))}
        </div>
      ) : (
        <form
          className="mt-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            answer(text);
          }}
        >
          <input className="sp-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Answer…" maxLength={500} aria-label={ask.question} />
        </form>
      )}
    </div>
  );
}
