import { useState } from "react";
import { Search } from "lucide-react";
import { useBrainGet } from "@/hooks/useBrainGet";
import { bareRules, matches, setBare, type Rule, type ToolRow } from "./logic";
import { ListState, Page, Seg, Tag } from "./ui";

// Capabilities (DESIGN.md §3): what Spark can do. Each tool shows where it runs, its risk, and a
// three-way control that writes a bare deny/ask/allow rule (Settings → Permissions lists them all).

const CHOICES = [
  { id: "allow", label: "Allow" },
  { id: "ask", label: "Ask" },
  { id: "deny", label: "Never" },
] as const;

export default function CapabilitiesPage() {
  const tools = useBrainGet<{ items: ToolRow[] }>("/v2/capabilities/tools");
  const rules = useBrainGet<{ items: Rule[] }>("/v2/permissions/rules");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const items = (tools.data?.items ?? []).filter((t) => matches(t, q));
  const all = rules.data?.items ?? [];

  const choose = async (tool: string, decision: Rule["decision"]): Promise<void> => {
    setError(await setBare(all, tool, decision));
    tools.reload();
    rules.reload();
  };

  return (
    <Page title="Capabilities">
      <div className="px-6 py-5">
        <label className="mb-4 flex h-10 items-center gap-2 rounded-xl border border-[var(--sp-line-2)] bg-[var(--sp-bg-2)] px-3 focus-within:border-[rgba(249,115,22,0.45)]">
          <Search className="size-4 text-[var(--sp-ink-4)]" />
          <input
            className="flex-1 bg-transparent text-[13.5px] text-[var(--sp-ink)] outline-none placeholder:text-[var(--sp-ink-4)]"
            placeholder="Search what Spark can do…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search tools"
          />
          <span className="text-[12px] text-[var(--sp-ink-4)]">{items.length} tools</span>
        </label>
        {error && (
          <p role="alert" className="mb-3 text-[13px] text-[var(--sp-err)]">
            {error}
          </p>
        )}
        <ListState loading={tools.loading} error={tools.error} empty={items.length === 0 && (q ? "Nothing matches that." : "No tools yet.")}>
          <table className="sp-table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Runs on</th>
                <th>Risk</th>
                <th>When Spark uses it</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => {
                const patterns = all.filter((r) => r.tool === t.name).length - bareRules(all, t.name).length;
                return (
                  <tr key={t.name}>
                    <td className="max-w-[420px]">
                      <div className="sp-mono text-[12.5px] text-[var(--sp-ink)]">{t.name}</div>
                      <div className="truncate text-[12px] text-[var(--sp-ink-4)]">{t.description}</div>
                    </td>
                    <td className="text-[12.5px]">{t.target === "brain" ? "Spark" : "Your device"}</td>
                    <td>
                      <Tag kind={t.risk} />
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <Seg label={`${t.name} permission`} value={t.permission === "review" ? null : t.permission} options={CHOICES} onChange={(d) => void choose(t.name, d)} />
                        {t.permission === "review" && <span className="text-[11.5px] text-[var(--sp-ink-4)]">auto-checked</span>}
                        {patterns > 0 && <span className="sp-mono text-[11px] text-[var(--sp-ink-4)]">+{patterns} rule{patterns > 1 ? "s" : ""}</span>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ListState>
      </div>
    </Page>
  );
}
