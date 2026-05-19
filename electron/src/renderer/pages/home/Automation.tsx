import { Bot } from "lucide-react";

export default function Automation() {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <Bot size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Automation</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="space-y-3 max-w-lg">
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">WhatsApp</p>
            <p className="text-xs text-slate-500 mt-0.5">Automated messaging and responses</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Email Automation</p>
            <p className="text-xs text-slate-500 mt-0.5">Auto-reply and email workflows</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Scheduled Tasks</p>
            <p className="text-xs text-slate-500 mt-0.5">Recurring actions and reminders</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Social Media</p>
            <p className="text-xs text-slate-500 mt-0.5">Cross-platform posting and monitoring</p>
          </div>
        </div>
      </div>
    </div>
  );
}
