import { Globe } from "lucide-react";

export default function ExternalServices() {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <Globe size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">External Services</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="space-y-3 max-w-lg">
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg flex items-center justify-between">
            <div>
              <p className="text-sm text-white">Google (Gmail, Calendar)</p>
              <p className="text-xs text-slate-500 mt-0.5">OAuth connected services</p>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">Not connected</span>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg flex items-center justify-between">
            <div>
              <p className="text-sm text-white">Spotify</p>
              <p className="text-xs text-slate-500 mt-0.5">Music playback integration</p>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">Not connected</span>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg flex items-center justify-between">
            <div>
              <p className="text-sm text-white">GitHub</p>
              <p className="text-xs text-slate-500 mt-0.5">Repository and code access</p>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">Not connected</span>
          </div>
        </div>
      </div>
    </div>
  );
}
