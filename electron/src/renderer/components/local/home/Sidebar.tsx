import { Activity, Clock, Settings, Globe, Bot, CalendarDays } from "lucide-react";

export type SidebarItem = "history" | "spark-logs" | "settings" | "external-services" | "automation" | "bookings";

interface SidebarProps {
  active: SidebarItem;
  onChange: (item: SidebarItem) => void;
}

const navItems: { id: SidebarItem; label: string; icon: typeof Activity }[] = [
  { id: "history", label: "History", icon: Clock },
  { id: "spark-logs", label: "Spark Logs", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "external-services", label: "External Services", icon: Globe },
  { id: "automation", label: "Automation", icon: Bot },
  { id: "bookings", label: "Bookings", icon: CalendarDays },
];

export default function Sidebar({ active, onChange }: SidebarProps) {
  return (
    <aside className="w-56 h-full bg-[#0c0c14] border-r border-slate-800 flex flex-col py-4 px-2">
      <div className="px-3 mb-4">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Navigation</span>
      </div>
      <nav className="flex-1 flex flex-col gap-0.5">
        {navItems.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onChange(id)}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
              active === id
                ? "bg-blue-600/15 text-blue-400"
                : "text-slate-400 hover:text-white hover:bg-slate-800/60"
            }`}
          >
            <Icon size={16} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
