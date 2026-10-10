import { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft } from "lucide-react";
import { filterCommands, type Command } from "./logic";

// Ctrl+K (DESIGN.md §3): every page, settings section and action, keyboard first.

export default function Palette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const shown = useMemo(() => filterCommands(commands, q), [commands, q]);
  useEffect(() => {
    input.current?.focus();
  }, []);

  const run = (c: Command | undefined): void => {
    if (!c) return;
    onClose();
    c.run();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[14vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-[560px] overflow-hidden rounded-2xl border border-[var(--sp-line-2)] bg-[var(--sp-bg-2)] shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={input}
          className="h-12 w-full border-b border-[var(--sp-line)] bg-transparent px-4 text-[14px] text-[var(--sp-ink)] outline-none placeholder:text-[var(--sp-ink-4)]"
          placeholder="Go to a page, change a setting, run an action…"
          value={q}
          aria-label="Search actions"
          onChange={(e) => {
            setQ(e.target.value);
            setAt(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") setAt((i) => Math.min(i + 1, shown.length - 1));
            else if (e.key === "ArrowUp") setAt((i) => Math.max(i - 1, 0));
            else if (e.key === "Enter") run(shown[at]);
            else return;
            e.preventDefault();
          }}
        />
        <div className="sp-scroll max-h-[360px] overflow-y-auto py-1.5" role="listbox">
          {shown.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-[var(--sp-ink-4)]">Nothing matches.</p>}
          {shown.map((c, i) => (
            <div key={c.id}>
              {(i === 0 || shown[i - 1].group !== c.group) && <p className="px-4 pb-1 pt-2 text-[11px] uppercase tracking-[0.08em] text-[var(--sp-ink-4)]">{c.group}</p>}
              <button
                role="option"
                aria-selected={i === at}
                className={`flex w-full items-center gap-2 px-4 py-2 text-left text-[13.5px] ${i === at ? "bg-[var(--sp-bg-3)] text-[var(--sp-ink)]" : "text-[var(--sp-ink-2)]"}`}
                onMouseEnter={() => setAt(i)}
                onClick={() => run(c)}
              >
                <span className="flex-1">{c.label}</span>
                {i === at && <CornerDownLeft className="size-3.5 text-[var(--sp-ink-4)]" />}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
