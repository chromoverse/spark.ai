import { Settings as SettingsIcon } from "lucide-react";

export default function SettingsPage() {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <SettingsIcon size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Settings</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="space-y-6 max-w-lg">
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Spark Internal</h3>
            <div className="space-y-3">
              <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <p className="text-sm text-white">Voice Engine</p>
                <p className="text-xs text-slate-500 mt-0.5">Configure TTS engine preferences</p>
              </div>
              <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <p className="text-sm text-white">LLM Provider</p>
                <p className="text-xs text-slate-500 mt-0.5">Manage API keys and model selection</p>
              </div>
              <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <p className="text-sm text-white">Memory & Context</p>
                <p className="text-xs text-slate-500 mt-0.5">Conversation memory and retrieval settings</p>
              </div>
            </div>
          </section>
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Application</h3>
            <div className="space-y-3">
              <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <p className="text-sm text-white">Notifications</p>
                <p className="text-xs text-slate-500 mt-0.5">Desktop notification preferences</p>
              </div>
              <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <p className="text-sm text-white">Privacy</p>
                <p className="text-xs text-slate-500 mt-0.5">Data handling and local storage</p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
