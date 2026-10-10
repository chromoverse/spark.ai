import type { ReactNode } from "react";

// Small pieces every Spark page shares (DESIGN.md §2, docs/mockups/r2-ui.html).

export function Page({ title, actions, tabs, children }: { title: string; actions?: ReactNode; tabs?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--sp-line)] px-6">
        <h2 className="text-[15px] font-semibold tracking-tight text-[var(--sp-ink)]">{title}</h2>
        <div className="flex-1" />
        {actions}
      </div>
      {tabs}
      <div className="sp-scroll min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: readonly { id: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex shrink-0 gap-5 border-b border-[var(--sp-line)] px-6" role="tablist">
      {options.map((o) => (
        <button
          key={o.id}
          role="tab"
          aria-selected={value === o.id}
          onClick={() => onChange(o.id)}
          className={`-mb-px border-b-2 py-2.5 text-[13px] transition-colors ${value === o.id ? "border-[var(--sp-accent)] text-[var(--sp-ink)]" : "border-transparent text-[var(--sp-ink-3)] hover:text-[var(--sp-ink-2)]"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange, label }: { value: T | null; options: readonly { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="sp-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} role="radio" aria-checked={value === o.id} className={value === o.id ? "on" : ""} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tag({ kind, label }: { kind: string; label?: string }) {
  return <span className={`sp-tag sp-tag-${kind}`}>{label ?? kind}</span>;
}

const DOT: Record<string, string> = {
  ok: "var(--sp-ok)",
  warn: "var(--sp-warn)",
  err: "var(--sp-err)",
  info: "var(--sp-info)",
  off: "var(--sp-ink-4)",
};

export function Dot({ tone }: { tone: keyof typeof DOT }) {
  return <span className="inline-block size-1.5 shrink-0 rounded-full" style={{ background: DOT[tone] }} />;
}

/** Every list has an empty, a loading and an error state (TESTING §4.11). */
export function ListState({ loading, error, empty, children }: { loading: boolean; error: string | null; empty: string | false; children: ReactNode }) {
  if (loading) return <p className="px-6 py-10 text-center text-[13px] text-[var(--sp-ink-4)]">Loading…</p>;
  if (error) return <p className="px-6 py-10 text-center text-[13px] text-[var(--sp-err)]">{error}</p>;
  if (empty) return <p className="px-6 py-10 text-center text-[13px] text-[var(--sp-ink-3)]">{empty}</p>;
  return <>{children}</>;
}
