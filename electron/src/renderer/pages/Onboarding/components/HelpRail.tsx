import { CirclePlay, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import type { HelpLink } from "../types";

interface HelpRailProps {
  title: string;
  description: string;
  links: HelpLink[];
}

export default function HelpRail({
  title,
  description,
  links,
}: HelpRailProps) {
  const handleOpen = async (url: string) => {
    try {
      await window.electronApi.openExternalUrl(url);
    } catch (error) {
      console.error("Failed to open onboarding help URL", error);
      toast.error("Spark could not open the help link.");
    }
  };

  return (
    <aside className="rounded-[28px] border border-white/12 bg-[linear-gradient(180deg,rgba(16,22,38,0.8),rgba(9,14,28,0.65))] p-5 backdrop-blur-xl">
      <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1.5 text-[10px] uppercase tracking-[0.24em] text-cyan-100">
        <CirclePlay size={12} />
        See how to get API key
      </div>
      <h3 className="mt-4 text-lg font-semibold text-white">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-slate-300">{description}</p>
      <div className="mt-4 space-y-3">
        {links.map((link) => (
          <button
            key={link.label}
            type="button"
            onClick={() => void handleOpen(link.url)}
            className="flex w-full items-start justify-between gap-4 rounded-[20px] border border-white/10 bg-white/6 px-4 py-3.5 text-left transition-all duration-300 hover:border-white/22 hover:bg-white/10"
          >
            <div>
              <p className="text-sm font-semibold text-white">{link.label}</p>
              {link.description ? (
                <p className="mt-1 text-xs leading-6 text-slate-400">
                  {link.description}
                </p>
              ) : null}
            </div>
            <ExternalLink size={14} className="mt-0.5 shrink-0 text-slate-300" />
          </button>
        ))}
      </div>
    </aside>
  );
}
