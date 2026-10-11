import { useEffect, useState } from "react";
import { Check, Pencil, Trash2 } from "lucide-react";
import { useBrainGet } from "@/hooks/useBrainGet";
import { ago } from "./logic";
import { ListState, Tag } from "./ui";

// Settings → Memory (REDESIGN §8): everything Spark remembers about you, to read, fix, or forget.
// Memories the agent saved during a task wait here for your OK before Spark uses them.

export interface MemoryRow {
  id: string;
  kind: string;
  text: string;
  importance: number;
  confirmed: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

const KIND: Record<string, string> = {
  person: "Person",
  preference: "Preference",
  routine: "Routine",
  fact: "Fact",
  correction: "Correction",
};

export default function MemorySection() {
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  const list = useBrainGet<{ items: MemoryRow[] }>(q ? `/v2/memories?q=${encodeURIComponent(q)}` : "/v2/memories");
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const send = async (method: "PATCH" | "DELETE", id: string, body?: object): Promise<boolean> => {
    const r = await window.electronApi.brain.request(method, `/v2/memories/${id}`, body);
    setError(r.ok ? null : r.error.message);
    list.reload();
    return r.ok;
  };
  const save = async (): Promise<void> => {
    if (editing && (await send("PATCH", editing.id, { text: editing.text.trim() }))) setEditing(null);
  };
  const forget = (m: MemoryRow): void => {
    if (window.confirm("Forget this? Spark won't know it again unless you tell it.")) void send("DELETE", m.id);
  };

  const items = list.data?.items ?? [];
  const waiting = items.some((m) => !m.confirmed);
  return (
    <div className="max-w-[760px]">
      <div className="flex items-end gap-4 pb-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] text-[var(--sp-ink)]">What Spark remembers</p>
          <p className="mt-0.5 text-[12.5px] text-[var(--sp-ink-4)]">It learns from what you tell it. Fix or forget anything here; “forget that…” works out loud too.</p>
        </div>
        <input className="sp-input w-[220px]" placeholder="Search memories" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={200} aria-label="Search memories" />
      </div>
      {waiting && <p className="mb-2 text-[12.5px] text-[var(--sp-ink-3)]">Some were saved during a task, maybe from a file or a page. Spark won't use them until you keep them.</p>}
      {error && (
        <p role="alert" className="mb-2 text-[13px] text-[var(--sp-err)]">
          {error}
        </p>
      )}
      <ListState loading={list.loading} error={list.error} empty={items.length === 0 && (q ? "Nothing matches that." : "Nothing yet. Tell Spark about yourself (“my sister is Asha”) and it'll remember.")}>
        <ul className="divide-y divide-[var(--sp-line)] border-y border-[var(--sp-line)]">
          {items.map((m) => (
            <li key={m.id} className="flex items-start gap-2 py-3">
              <div className="min-w-0 flex-1">
                {editing?.id === m.id ? (
                  <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void save();
                    }}
                  >
                    <input className="sp-input flex-1" value={editing.text} onChange={(e) => setEditing({ id: m.id, text: e.target.value })} maxLength={500} aria-label="Memory" autoFocus />
                    <button className="sp-btn-accent px-3" type="submit" disabled={!editing.text.trim()}>
                      Save
                    </button>
                    <button className="sp-btn-ghost px-3" type="button" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <p className="text-[13.5px] text-[var(--sp-ink)]">{m.text}</p>
                )}
                <p className="mt-0.5 text-[12px] text-[var(--sp-ink-4)]">
                  {[KIND[m.kind] ?? m.kind, m.last_used_at ? `used ${ago(m.last_used_at)}` : `added ${ago(m.created_at)}`, m.expires_at ? "fades if unused" : null].filter(Boolean).join(" · ")}
                </p>
              </div>
              {!m.confirmed && (
                <>
                  <Tag kind="ask" label="needs your OK" />
                  <button className="sp-btn-ghost h-8 gap-1 px-2 text-[12.5px]" onClick={() => void send("PATCH", m.id, { confirmed: true })} aria-label={`Keep: ${m.text}`}>
                    <Check className="size-3.5" /> Keep
                  </button>
                </>
              )}
              <button className="sp-btn-ghost size-8 min-w-8" onClick={() => setEditing({ id: m.id, text: m.text })} aria-label={`Edit: ${m.text}`}>
                <Pencil className="size-3.5" />
              </button>
              <button className="sp-btn-ghost size-8 min-w-8" onClick={() => forget(m)} aria-label={`Forget: ${m.text}`}>
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </ListState>
    </div>
  );
}
