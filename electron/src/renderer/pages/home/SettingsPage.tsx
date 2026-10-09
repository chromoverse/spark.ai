import { Settings as SettingsIcon, Pencil, Trash2, Plus, X } from "lucide-react";
import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { useState } from "react";
import axiosInstance from "@/utils/axiosConfig";
import { toast } from "sonner";
import { getCurrentUser } from "@/store/features/auth/authThunks";

export default function SettingsPage() {
  const { user } = useAppSelector((state) => state.auth);
  const dispatch = useAppDispatch();

  const [editField, setEditField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);

  const [selectedKeys, setSelectedKeys] = useState<{ provider: string; indices: number[] }>({ provider: "", indices: [] });
  const [verifyStep, setVerifyStep] = useState<"idle" | "select" | "verify" | "code">("idle");
  const [otp, setOtp] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [addKeyProvider, setAddKeyProvider] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");

  const save = async (field: string, value: any) => {
    if (!user?._id) return;
    setSaving(true);
    try {
      await axiosInstance.patch(`/auth/update-user-details?userId=${user._id}`, { [field]: value });
      await dispatch(getCurrentUser());
      toast.success("Updated");
      setEditField(null);
    } catch { toast.error("Failed to save"); }
    finally { setSaving(false); }
  };

  const startEdit = (field: string, current: string) => { setEditField(field); setEditValue(current); };

  const handleAddKey = async () => {
    if (!newKey.trim() || !addKeyProvider || !user?._id) return;
    const existing = (user as any)?.apiKeys?.[addKeyProvider] || [];
    await save("api_keys", { ...((user as any)?.apiKeys || {}), [addKeyProvider]: [...existing, newKey.trim()] });
    setNewKey("");
    setAddKeyProvider(null);
  };

  const startDeleteFlow = (provider: string) => { setSelectedKeys({ provider, indices: [] }); setVerifyStep("select"); };
  const toggleKeySelection = (idx: number) => {
    setSelectedKeys((prev) => ({
      ...prev,
      indices: prev.indices.includes(idx) ? prev.indices.filter((i) => i !== idx) : [...prev.indices, idx],
    }));
  };

  const requestVerification = async () => {
    if (!user?.email) return;
    setVerifying(true);
    try {
      await axiosInstance.post("/auth/sign-in", { email: user.email });
      toast.success("Code sent to your email");
      setVerifyStep("code");
    } catch { toast.error("Failed to send code"); }
    finally { setVerifying(false); }
  };

  const confirmDelete = async () => {
    if (!otp || otp.length !== 6 || !user?._id) return;
    setVerifying(true);
    try {
      const res = await axiosInstance.post("/auth/verify-otp", { email: user.email, otp });
      if (!res.success && !res.access_token) { toast.error("Invalid code"); setVerifying(false); return; }
      const existing: string[] = (user as any)?.apiKeys?.[selectedKeys.provider] || [];
      const filtered = existing.filter((_, i) => !selectedKeys.indices.includes(i));
      await axiosInstance.patch(`/auth/update-user-details?userId=${user._id}`, { api_keys: { ...((user as any)?.apiKeys || {}), [selectedKeys.provider]: filtered } });
      await dispatch(getCurrentUser());
      toast.success("Keys removed");
      setVerifyStep("idle"); setOtp(""); setSelectedKeys({ provider: "", indices: [] });
    } catch { toast.error("Verification failed"); }
    finally { setVerifying(false); }
  };

  const cancelFlow = () => { setVerifyStep("idle"); setOtp(""); setSelectedKeys({ provider: "", indices: [] }); };

  const keyProviders = [
    { id: "gemini",     label: "Gemini",     keys: (user as any)?.apiKeys?.gemini     || [] },
    { id: "groq",       label: "Groq",       keys: (user as any)?.apiKeys?.groq       || [] },
    { id: "openrouter", label: "OpenRouter", keys: (user as any)?.apiKeys?.openrouter || [] },
    { id: "cerebras",   label: "Cerebras",   keys: (user as any)?.apiKeys?.cerebras   || [] },
    { id: "sambanova",  label: "SambaNova",  keys: (user as any)?.apiKeys?.sambanova  || [] },
    { id: "mistral",    label: "Mistral",    keys: (user as any)?.apiKeys?.mistral    || [] },
    { id: "anthropic",  label: "Anthropic",  keys: (user as any)?.apiKeys?.anthropic  || [] },
  ];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)", fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ padding: "14px 24px 12px", borderBottom: "1px solid var(--sp-line)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <SettingsIcon size={15} style={{ color: "var(--sp-ink-3)" }} />
        <h2 className="sp-serif" style={{ margin: 0, fontSize: 20, color: "var(--sp-ink)", fontWeight: 400 }}>Settings</h2>
      </div>
      <div className="sp-scroll" style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        <div style={{ maxWidth: 600, margin: "0 auto", display: "flex", flexDirection: "column", gap: 28 }}>

          {/* Profile */}
          <section>
            <SectionLabel>Profile</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <EditableRow label="Username" value={user?.username || ""} field="username" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
              <Row label="Email" value={user?.email || "—"} />
              <EditableRow label="Language" value={user?.language || "en"} field="language" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
            </div>
          </section>

          {/* Voice */}
          <section>
            <SectionLabel>Voice</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <EditableRow label="Voice Gender" value={user?.aiGender || ""} field="ai_gender" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
              <EditableRow label="Voice Name" value={user?.aiVoiceName || ""} field="ai_voice_name" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
            </div>
          </section>

          {/* API Keys */}
          <section>
            <SectionLabel>API Keys</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {keyProviders.map((p) => (
                <div key={p.id} style={{ background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 8, padding: "12px 14px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 14, color: "var(--sp-ink)", fontWeight: 500 }}>{p.label}</span>
                    <div style={{ display: "flex", gap: 10 }}>
                      <button onClick={() => setAddKeyProvider(p.id)} style={{ fontSize: 11, color: "var(--sp-info)", background: "none", border: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
                        <Plus size={11} /> Add
                      </button>
                      {p.keys.filter(Boolean).length > 0 && (
                        <button onClick={() => startDeleteFlow(p.id)} style={{ fontSize: 11, color: "var(--sp-err)", background: "none", border: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
                          <Trash2 size={11} /> Remove
                        </button>
                      )}
                    </div>
                  </div>
                  {p.keys.filter(Boolean).length === 0 ? (
                    <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>No keys configured</p>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                      {p.keys.filter(Boolean).map((k, i) => (
                        <div key={i} style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "5px 9px", borderRadius: 5,
                          background: verifyStep !== "idle" && selectedKeys.provider === p.id && selectedKeys.indices.includes(i) ? "var(--sp-err-soft)" : "var(--sp-bg-3)",
                          border: `1px solid ${verifyStep !== "idle" && selectedKeys.provider === p.id && selectedKeys.indices.includes(i) ? "rgba(201,112,100,0.25)" : "var(--sp-line)"}`,
                        }}>
                          {verifyStep === "select" && selectedKeys.provider === p.id && (
                            <input type="checkbox" checked={selectedKeys.indices.includes(i)} onChange={() => toggleKeySelection(i)} style={{ accentColor: "var(--sp-err)" }} />
                          )}
                          <span className="sp-mono" style={{ fontSize: 12, color: "var(--sp-ink-3)" }}>{k.slice(0, 8)}…{k.slice(-4)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {addKeyProvider === p.id && (
                    <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
                      <input
                        value={newKey} onChange={(e) => setNewKey(e.target.value)}
                        placeholder="Paste API key"
                        style={{ flex: 1, padding: "6px 10px", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)", borderRadius: 6, fontSize: 12, color: "var(--sp-ink)", outline: "none", fontFamily: "'Geist Mono', monospace" }}
                      />
                      <button onClick={handleAddKey} disabled={saving} style={{ padding: "6px 12px", background: "var(--sp-accent)", color: "#1a1208", border: "none", borderRadius: 6, fontSize: 12, cursor: "pointer" }}>
                        Save
                      </button>
                      <button onClick={() => { setAddKeyProvider(null); setNewKey(""); }} style={{ padding: "6px 8px", background: "none", border: "1px solid var(--sp-line-2)", borderRadius: 6, color: "var(--sp-ink-3)", cursor: "pointer" }}>
                        <X size={13} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Verify & Delete flow */}
          {verifyStep === "select" && selectedKeys.indices.length > 0 && (
            <div style={{ padding: "14px 16px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line-2)", borderRadius: 8 }}>
              <p style={{ margin: "0 0 10px", fontSize: 13, color: "var(--sp-ink)" }}>Verify it's you to remove {selectedKeys.indices.length} key(s)</p>
              <button onClick={requestVerification} disabled={verifying} style={{ padding: "7px 14px", background: "var(--sp-err)", color: "#fff", border: "none", borderRadius: 6, fontSize: 12, cursor: "pointer" }}>
                {verifying ? "Sending…" : "Send verification code"}
              </button>
              <button onClick={cancelFlow} style={{ marginLeft: 10, fontSize: 12, color: "var(--sp-ink-3)", background: "none", border: 0, cursor: "pointer" }}>Cancel</button>
            </div>
          )}
          {verifyStep === "code" && (
            <div style={{ padding: "14px 16px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line-2)", borderRadius: 8 }}>
              <p style={{ margin: "0 0 10px", fontSize: 13, color: "var(--sp-ink)" }}>Enter the code sent to {user?.email}</p>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000" maxLength={6}
                  style={{ width: 110, padding: "7px 10px", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)", borderRadius: 6, textAlign: "center", fontSize: 14, color: "var(--sp-ink)", outline: "none", fontFamily: "'Geist Mono', monospace", letterSpacing: "0.2em" }}
                />
                <button onClick={confirmDelete} disabled={verifying || otp.length !== 6} style={{ padding: "7px 14px", background: "var(--sp-err)", color: "#fff", border: "none", borderRadius: 6, fontSize: 12, cursor: "pointer", opacity: otp.length !== 6 ? 0.5 : 1 }}>
                  {verifying ? "Verifying…" : "Confirm Delete"}
                </button>
                <button onClick={cancelFlow} style={{ fontSize: 12, color: "var(--sp-ink-3)", background: "none", border: 0, cursor: "pointer" }}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", letterSpacing: "0.12em", textTransform: "uppercase", margin: "0 0 8px 2px" }}>
      {children}
    </p>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7 }}>
      <span style={{ fontSize: 13, color: "var(--sp-ink-3)" }}>{label}</span>
      <span style={{ fontSize: 13, color: "var(--sp-ink)" }}>{value}</span>
    </div>
  );
}

function EditableRow({ label, value, field, editField, editValue, saving, onEdit, onSave, onChange, onCancel }: {
  label: string; value: string; field: string; editField: string | null; editValue: string; saving: boolean;
  onEdit: (f: string, v: string) => void; onSave: (f: string, v: any) => void; onChange: (v: string) => void; onCancel: () => void;
}) {
  const isEditing = editField === field;
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 12px", background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)", borderRadius: 7 }}>
      <span style={{ fontSize: 13, color: "var(--sp-ink-3)" }}>{label}</span>
      {isEditing ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            value={editValue} onChange={(e) => onChange(e.target.value)} autoFocus
            style={{ padding: "4px 8px", background: "var(--sp-bg-3)", border: "1px solid var(--sp-line-2)", borderRadius: 5, fontSize: 13, color: "var(--sp-ink)", outline: "none", width: 140 }}
          />
          <button onClick={() => onSave(field, editValue)} disabled={saving} style={{ fontSize: 11, color: "var(--sp-accent)", background: "none", border: 0, cursor: "pointer" }}>
            {saving ? "…" : "Save"}
          </button>
          <button onClick={onCancel} style={{ fontSize: 11, color: "var(--sp-ink-4)", background: "none", border: 0, cursor: "pointer" }}>✕</button>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, color: "var(--sp-ink)" }}>{value || "Not set"}</span>
          <button onClick={() => onEdit(field, value)} style={{ color: "var(--sp-ink-4)", background: "none", border: 0, cursor: "pointer", display: "flex" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)"; }}>
            <Pencil size={12} />
          </button>
        </div>
      )}
    </div>
  );
}
