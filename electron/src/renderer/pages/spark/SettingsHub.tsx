import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";
import type { IBrainSettings } from "@root/types";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { resetUser } from "@/store/features/auth/authSlice";
import { useBrainGet } from "@/hooks/useBrainGet";
import { ago, type Rule, type ToolRow } from "./logic";
import MemorySection from "./MemorySection";
import { Dot, ListState, Page, Seg, Tag } from "./ui";

// Settings (DESIGN.md §3): you and your data, in sections. Changes PATCH /v2/settings; the brain
// pushes settings.changed to every device (this one included), which updates the store.

export const SECTIONS = [
  { id: "account", label: "Account" },
  { id: "devices", label: "Devices" },
  { id: "permissions", label: "Permissions" },
  { id: "memory", label: "Memory" },
  { id: "privacy", label: "Privacy & voice" },
] as const;
export type Section = (typeof SECTIONS)[number]["id"];

async function patch(change: Partial<IBrainSettings>): Promise<string | null> {
  const r = await window.electronApi.brain.request("PATCH", "/v2/settings", change);
  return r.ok ? null : r.error.message;
}

export default function SettingsHub({ section, onSection }: { section: Section; onSection: (s: Section) => void }) {
  return (
    <Page title="Settings">
      <div className="flex min-h-full">
        <nav className="flex w-[200px] shrink-0 flex-col gap-0.5 border-r border-[var(--sp-line)] p-3">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              onClick={() => onSection(s.id)}
              className={`rounded-lg px-3 py-2 text-left text-[13px] transition-colors ${section === s.id ? "bg-[var(--sp-bg-3)] text-[var(--sp-ink)]" : "text-[var(--sp-ink-3)] hover:text-[var(--sp-ink)]"}`}
            >
              {s.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1 px-8 py-6">
          {section === "account" && <Account />}
          {section === "devices" && <Devices />}
          {section === "permissions" && <Permissions />}
          {section === "memory" && <MemorySection />}
          {section === "privacy" && <Privacy />}
        </div>
      </div>
    </Page>
  );
}

function Field({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-6 border-b border-[var(--sp-line)] py-4">
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] text-[var(--sp-ink)]">{title}</p>
        {hint && <p className="mt-0.5 text-[12.5px] text-[var(--sp-ink-4)]">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function Account() {
  const user = useAppSelector((s) => s.auth.user);
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const signOut = async (): Promise<void> => {
    await window.electronApi.brain.signOut();
    dispatch(resetUser());
    navigate("/welcome");
  };
  return (
    <div className="max-w-[640px]">
      <Field title={user?.fullName ?? "Signed in"} hint={user?.email}>
        <button className="sp-btn-ghost px-3" onClick={() => void signOut()}>
          Sign out
        </button>
      </Field>
    </div>
  );
}

interface Device {
  id: string;
  name: string;
  kind: string;
  platform: string | null;
  is_default_for: string[];
  last_seen_at: string | null;
  online: boolean;
  current: boolean;
}

function Devices() {
  const devices = useBrainGet<{ items: Device[] }>("/v2/devices");
  const [error, setError] = useState<string | null>(null);
  const remove = async (d: Device): Promise<void> => {
    if (!window.confirm(`Forget ${d.name}? It gets signed out.`)) return;
    const r = await window.electronApi.brain.request("DELETE", `/v2/devices/${d.id}`);
    setError(r.ok ? null : r.error.message);
    devices.reload();
  };
  const items = devices.data?.items ?? [];
  return (
    <div className="max-w-[760px]">
      {error && <p role="alert" className="mb-3 text-[13px] text-[var(--sp-err)]">{error}</p>}
      <ListState loading={devices.loading} error={devices.error} empty={items.length === 0 && "No devices yet."}>
        <table className="sp-table">
          <tbody>
            {items.map((d) => (
              <tr key={d.id}>
                <td>
                  <div className="flex items-center gap-2 text-[var(--sp-ink)]">
                    <Dot tone={d.online ? "ok" : "off"} />
                    {d.name}
                    {d.current && <span className="text-[11.5px] text-[var(--sp-ink-4)]">this device</span>}
                  </div>
                  <div className="mt-0.5 text-[12px] text-[var(--sp-ink-4)]">
                    {[d.kind, d.platform, d.is_default_for.length ? `“my ${d.is_default_for.join("”, “my ")}”` : null].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td className="text-[12px] text-[var(--sp-ink-4)]">{d.online ? "online" : d.last_seen_at ? `seen ${ago(d.last_seen_at)}` : ""}</td>
                <td className="w-10">
                  {!d.current && (
                    <button className="sp-btn-ghost size-8 min-w-8" onClick={() => void remove(d)} aria-label={`Forget ${d.name}`}>
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ListState>
    </div>
  );
}

const MODES = [
  { id: "default", label: "Default" },
  { id: "ask", label: "Ask for everything" },
  { id: "trust", label: "Trust" },
] as const;
const DECISIONS = [
  { id: "deny", label: "Never" },
  { id: "ask", label: "Ask" },
  { id: "allow", label: "Allow" },
] as const;

function Permissions() {
  const mode = useAppSelector((s) => s.brain.settings?.permission_mode ?? "default");
  const rules = useBrainGet<{ items: Rule[] }>("/v2/permissions/rules");
  const tools = useBrainGet<{ items: ToolRow[] }>("/v2/capabilities/tools");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ tool: string; pattern: string; decision: Rule["decision"] }>({ tool: "", pattern: "", decision: "ask" });

  const add = async (): Promise<void> => {
    const r = await window.electronApi.brain.request("POST", "/v2/permissions/rules", { tool: draft.tool, pattern: draft.pattern.trim(), decision: draft.decision });
    setError(r.ok ? null : r.error.message);
    if (r.ok) setDraft({ tool: "", pattern: "", decision: "ask" });
    rules.reload();
  };
  const remove = async (id: string): Promise<void> => {
    const r = await window.electronApi.brain.request("DELETE", `/v2/permissions/rules/${id}`);
    setError(r.ok ? null : r.error.message);
    rules.reload();
  };
  const items = rules.data?.items ?? [];

  return (
    <div className="max-w-[820px]">
      <Field title="Permission mode" hint="How careful Spark is before it acts.">
        <Seg label="Permission mode" value={mode} options={MODES} onChange={(m) => void patch({ permission_mode: m }).then(setError)} />
      </Field>
      <div className="pb-2 pt-5">
        <p className="text-[13.5px] text-[var(--sp-ink)]">Rules</p>
        <p className="mt-0.5 text-[12.5px] text-[var(--sp-ink-4)]">Never beats ask beats allow. A rule with no pattern covers every call.</p>
      </div>
      {error && <p role="alert" className="my-2 text-[13px] text-[var(--sp-err)]">{error}</p>}
      <form
        className="mb-3 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.tool) void add();
        }}
      >
        <select className="sp-input w-[200px]" value={draft.tool} onChange={(e) => setDraft({ ...draft, tool: e.target.value })} aria-label="Tool">
          <option value="">Tool…</option>
          {(tools.data?.items ?? []).map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>
        <input className="sp-input sp-mono flex-1" placeholder="Pattern, e.g. C:/Users/*/Documents/** (optional)" value={draft.pattern} onChange={(e) => setDraft({ ...draft, pattern: e.target.value })} maxLength={500} aria-label="Pattern" />
        <Seg label="Decision" value={draft.decision} options={DECISIONS} onChange={(d) => setDraft({ ...draft, decision: d })} />
        <button className="sp-btn-accent px-3" type="submit" disabled={!draft.tool}>
          Add
        </button>
      </form>
      <ListState loading={rules.loading} error={rules.error} empty={items.length === 0 && "No rules yet. “Always allow” on an approval adds one here."}>
        <table className="sp-table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Pattern</th>
              <th>Decision</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className="sp-mono text-[12.5px] text-[var(--sp-ink)]">{r.tool}</td>
                <td className="sp-mono text-[12px]">{r.pattern || <span className="text-[var(--sp-ink-4)]">every call</span>}</td>
                <td>
                  <Tag kind={r.decision} />
                </td>
                <td className="w-10">
                  <button className="sp-btn-ghost size-8 min-w-8" onClick={() => void remove(r.id)} aria-label={`Remove rule for ${r.tool}`}>
                    <Trash2 className="size-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ListState>
    </div>
  );
}

const VERBOSITY = [
  { id: "brief", label: "Brief" },
  { id: "normal", label: "Normal" },
  { id: "detailed", label: "Detailed" },
] as const;

function Privacy() {
  const settings = useAppSelector((s) => s.brain.settings);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  if (!settings) return <p className="text-[13px] text-[var(--sp-ink-4)]">Loading…</p>;
  const save = (change: Partial<IBrainSettings>): void => void patch(change).then(setError);
  return (
    <div className="max-w-[640px]">
      {error && <p role="alert" className="mb-2 text-[13px] text-[var(--sp-err)]">{error}</p>}
      <Field title="How much Spark says" hint="Brief keeps spoken replies to a sentence or two.">
        <Seg label="Verbosity" value={settings.verbosity} options={VERBOSITY} onChange={(v) => save({ verbosity: v })} />
      </Field>
      <Field title="What Spark calls you" hint="Leave empty to use your name.">
        <input
          className="sp-input w-[200px]"
          value={name ?? settings.address_as ?? ""}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name === null) return;
            save({ address_as: name.trim() || null });
            setName(null);
          }}
          maxLength={40}
          aria-label="What Spark calls you"
        />
      </Field>
      <Field title="Use models that train on your data" hint="Some free models (Gemini) learn from what you send. Off keeps them out of every chain.">
        <button
          role="switch"
          aria-checked={settings.allow_training_providers}
          onClick={() => save({ allow_training_providers: !settings.allow_training_providers })}
          className={`relative h-5 w-9 rounded-full transition-colors ${settings.allow_training_providers ? "bg-[var(--sp-accent)]" : "bg-[var(--sp-line-2)]"}`}
        >
          <span className={`absolute top-0.5 size-4 rounded-full bg-white transition-all ${settings.allow_training_providers ? "left-[18px]" : "left-0.5"}`} />
        </button>
      </Field>
    </div>
  );
}
