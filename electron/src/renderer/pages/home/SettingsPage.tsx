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

  // API key deletion flow
  const [selectedKeys, setSelectedKeys] = useState<{ provider: string; indices: number[] }>({ provider: "", indices: [] });
  const [verifyStep, setVerifyStep] = useState<"idle" | "select" | "verify" | "code">("idle");
  const [otp, setOtp] = useState("");
  const [verifying, setVerifying] = useState(false);

  // Add key flow
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

  const startEdit = (field: string, current: string) => {
    setEditField(field);
    setEditValue(current);
  };

  const handleAddKey = async () => {
    if (!newKey.trim() || !addKeyProvider || !user?._id) return;
    const fieldMap: Record<string, string> = { gemini: "gemini_api_keys", groq: "groq_api_keys", openrouter: "openrouter_api_keys" };
    const userFieldMap: Record<string, string> = { gemini: "geminiApiKeys", groq: "groqApiKeys", openrouter: "openrouterApiKeys" };
    const existing = (user as any)[userFieldMap[addKeyProvider]] || [];
    await save(fieldMap[addKeyProvider], [...existing, newKey.trim()]);
    setNewKey("");
    setAddKeyProvider(null);
  };

  const startDeleteFlow = (provider: string) => {
    setSelectedKeys({ provider, indices: [] });
    setVerifyStep("select");
  };

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
      // Verify OTP first
      const res = await axiosInstance.post("/auth/verify-otp", { email: user.email, otp });
      if (!res.success && !res.access_token) { toast.error("Invalid code"); setVerifying(false); return; }

      // Now delete selected keys
      const fieldMap: Record<string, string> = { gemini: "gemini_api_keys", groq: "groq_api_keys", openrouter: "openrouter_api_keys" };
      const userFieldMap: Record<string, string> = { gemini: "geminiApiKeys", groq: "groqApiKeys", openrouter: "openrouterApiKeys" };
      const existing: string[] = (user as any)[userFieldMap[selectedKeys.provider]] || [];
      const filtered = existing.filter((_, i) => !selectedKeys.indices.includes(i));
      await axiosInstance.patch(`/auth/update-user-details?userId=${user._id}`, { [fieldMap[selectedKeys.provider]]: filtered });
      await dispatch(getCurrentUser());
      toast.success("Keys removed");
      setVerifyStep("idle");
      setOtp("");
      setSelectedKeys({ provider: "", indices: [] });
    } catch { toast.error("Verification failed"); }
    finally { setVerifying(false); }
  };

  const cancelFlow = () => { setVerifyStep("idle"); setOtp(""); setSelectedKeys({ provider: "", indices: [] }); };

  const keyProviders = [
    { id: "gemini", label: "Gemini", keys: user?.geminiApiKeys || [] },
    { id: "groq", label: "Groq", keys: user?.groqApiKeys || [] },
    { id: "openrouter", label: "OpenRouter", keys: user?.openrouterApiKeys || [] },
  ];

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-6 py-4 border-b border-slate-800">
        <SettingsIcon size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Spark Settings</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-xl space-y-6">

          {/* Editable fields */}
          <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Profile</h3>
            <div className="space-y-1.5">
              <EditableRow label="Username" value={user?.username || ""} field="username" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
              <Row label="Email" value={user?.email || "—"} />
              <EditableRow label="Language" value={user?.language || "en"} field="language" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Voice</h3>
            <div className="space-y-1.5">
              <EditableRow label="Voice Gender" value={user?.aiGender || ""} field="ai_gender" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
              <EditableRow label="Voice Name" value={user?.aiVoiceName || ""} field="ai_voice_name" editField={editField} editValue={editValue} saving={saving} onEdit={startEdit} onSave={save} onChange={setEditValue} onCancel={() => setEditField(null)} />
            </div>
          </section>

          {/* API Keys */}
          <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">API Keys</h3>
            <div className="space-y-4">
              {keyProviders.map((p) => (
                <div key={p.id} className="bg-slate-900/40 border border-slate-800 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-white font-medium">{p.label}</span>
                    <div className="flex gap-2">
                      <button onClick={() => setAddKeyProvider(p.id)} className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1"><Plus size={12} /> Add</button>
                      {p.keys.filter(Boolean).length > 0 && (
                        <button onClick={() => startDeleteFlow(p.id)} className="text-[11px] text-red-400 hover:text-red-300 flex items-center gap-1"><Trash2 size={12} /> Remove</button>
                      )}
                    </div>
                  </div>
                  {p.keys.filter(Boolean).length === 0 ? (
                    <p className="text-xs text-slate-600">No keys configured</p>
                  ) : (
                    <div className="space-y-1">
                      {p.keys.filter(Boolean).map((k, i) => (
                        <div key={i} className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded ${
                          verifyStep !== "idle" && selectedKeys.provider === p.id && selectedKeys.indices.includes(i) ? "bg-red-500/10 border border-red-500/30" : "bg-slate-800/50"
                        }`}>
                          {verifyStep === "select" && selectedKeys.provider === p.id && (
                            <input type="checkbox" checked={selectedKeys.indices.includes(i)} onChange={() => toggleKeySelection(i)} className="accent-red-500" />
                          )}
                          <span className="text-slate-400 font-mono">{k.slice(0, 8)}...{k.slice(-4)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add key inline */}
                  {addKeyProvider === p.id && (
                    <div className="mt-2 flex gap-2">
                      <input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="Paste API key" className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs text-white placeholder-slate-500 focus:outline-none focus:border-slate-500" />
                      <button onClick={handleAddKey} disabled={saving} className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-xs text-white">Save</button>
                      <button onClick={() => { setAddKeyProvider(null); setNewKey(""); }} className="px-2 py-1.5 text-slate-400 hover:text-white"><X size={14} /></button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Verify & Delete flow */}
          {verifyStep === "select" && selectedKeys.indices.length > 0 && (
            <div className="p-4 bg-slate-900 border border-slate-700 rounded-lg">
              <p className="text-sm text-white mb-3">Verify it's you to remove {selectedKeys.indices.length} key(s)</p>
              <button onClick={requestVerification} disabled={verifying} className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded-lg text-sm text-white">
                {verifying ? "Sending..." : "Send verification code"}
              </button>
              <button onClick={cancelFlow} className="ml-3 text-sm text-slate-400 hover:text-white">Cancel</button>
            </div>
          )}

          {verifyStep === "code" && (
            <div className="p-4 bg-slate-900 border border-slate-700 rounded-lg">
              <p className="text-sm text-white mb-3">Enter the code sent to {user?.email}</p>
              <div className="flex gap-2">
                <input value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" className="w-32 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-center text-white font-mono tracking-widest focus:outline-none focus:border-slate-500" maxLength={6} />
                <button onClick={confirmDelete} disabled={verifying || otp.length !== 6} className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded text-sm text-white">
                  {verifying ? "Verifying..." : "Confirm Delete"}
                </button>
                <button onClick={cancelFlow} className="text-sm text-slate-400 hover:text-white">Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="text-sm text-white">{value}</span>
    </div>
  );
}

function EditableRow({ label, value, field, editField, editValue, saving, onEdit, onSave, onChange, onCancel }: {
  label: string; value: string; field: string; editField: string | null; editValue: string; saving: boolean;
  onEdit: (f: string, v: string) => void; onSave: (f: string, v: any) => void; onChange: (v: string) => void; onCancel: () => void;
}) {
  const isEditing = editField === field;
  return (
    <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/40 border border-slate-800 rounded-lg">
      <span className="text-sm text-slate-400">{label}</span>
      {isEditing ? (
        <div className="flex items-center gap-2">
          <input value={editValue} onChange={(e) => onChange(e.target.value)} className="px-2 py-1 bg-slate-800 border border-slate-600 rounded text-sm text-white w-40 focus:outline-none" autoFocus />
          <button onClick={() => onSave(field, editValue)} disabled={saving} className="text-xs text-blue-400 hover:text-blue-300">{saving ? "..." : "Save"}</button>
          <button onClick={onCancel} className="text-xs text-slate-500 hover:text-white">✕</button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-sm text-white">{value || "Not set"}</span>
          <button onClick={() => onEdit(field, value)} className="text-slate-600 hover:text-slate-300"><Pencil size={12} /></button>
        </div>
      )}
    </div>
  );
}
