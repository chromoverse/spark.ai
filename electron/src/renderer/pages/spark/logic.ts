// The Spark pages' plain logic (no React), kept apart so it's tested on its own.

export interface ToolRow {
  name: string;
  description: string;
  target: "brain" | "device";
  risk: string;
  permission: "allow" | "review" | "ask" | "deny";
}

export interface Rule {
  id: string;
  tool: string;
  pattern: string;
  decision: "allow" | "ask" | "deny";
  device_id: string | null;
}

export interface Command {
  id: string;
  group: string;
  label: string;
  keywords?: string;
  run: () => void;
}

/** The tool's bare rules (no pattern, every device): the ones the three-way control owns. */
export const bareRules = (rules: Rule[], tool: string): Rule[] => rules.filter((r) => r.tool === tool && !r.pattern && !r.device_id);

/** One bare rule per tool: replace what's there with the new decision. → an error message or null. */
export async function setBare(rules: Rule[], tool: string, decision: Rule["decision"]): Promise<string | null> {
  for (const r of bareRules(rules, tool)) {
    const d = await window.electronApi.brain.request("DELETE", `/v2/permissions/rules/${r.id}`);
    if (!d.ok) return d.error.message;
  }
  const r = await window.electronApi.brain.request("POST", "/v2/permissions/rules", { tool, decision });
  return r.ok ? null : r.error.message;
}

/** Every typed word appears in the tool's name or description ("clip" finds clipboard_read). */
export function matches(t: ToolRow, q: string): boolean {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hay = `${t.name.replaceAll("_", " ")} ${t.name} ${t.description}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** Every typed word must start a word of the label, keywords or group ("perm" → Permissions). */
export function filterCommands(commands: Command[], q: string): Command[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return commands;
  return commands.filter((c) => {
    const hay = `${c.label} ${c.keywords ?? ""} ${c.group}`.toLowerCase().split(/[^a-z0-9+]+/);
    return words.every((w) => hay.some((h) => h.startsWith(w)));
  });
}

export function fmtEta(s: number): string {
  if (s < 60) return `${Math.max(1, Math.round(s))} seconds`;
  const m = Math.round(s / 60);
  return m === 1 ? "a minute" : `${m} minutes`;
}

const UNITS: [number, string][] = [
  [86_400, "d"],
  [3_600, "h"],
  [60, "min"],
];

/** "just now", "4 min ago", "2 h ago", "3 d ago". */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  for (const [n, unit] of UNITS) if (s >= n) return `${Math.floor(s / n)} ${unit} ago`;
  return "just now";
}
