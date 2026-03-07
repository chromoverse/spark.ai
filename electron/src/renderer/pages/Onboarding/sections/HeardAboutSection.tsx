import {
  Github,
  Globe,
  Instagram,
  Linkedin,
  MessageCircle,
  MessageSquare,
  Twitter,
  Users,
  Youtube,
} from "lucide-react";
import SectionHeader from "../components/SectionHeader";
import type { ChoiceOption } from "../types";

interface HeardAboutSectionProps {
  eyebrow: string;
  title: string;
  description: string;
  options: ChoiceOption[];
  value: string;
  customValue: string;
  onChange: (value: string) => void;
  onCustomValueChange: (value: string) => void;
}

export default function HeardAboutSection({
  eyebrow,
  title,
  description,
  options,
  value,
  customValue,
  onChange,
  onCustomValueChange,
}: HeardAboutSectionProps) {
  const showCustomInput = value === "other";
  const iconMap = {
    youtube: Youtube,
    instagram: Instagram,
    twitter: Twitter,
    linkedin: Linkedin,
    github: Github,
    users: Users,
    globe: Globe,
    reddit: MessageCircle,
    discord: MessageSquare,
  } as const;

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {options.map((option) => {
          const Icon =
            iconMap[(option.iconKey as keyof typeof iconMap) ?? "globe"] ?? Globe;

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={`rounded-[22px] border px-4 py-4 text-left transition-all duration-300 ${
                value === option.value
                  ? "border-cyan-300/60 bg-cyan-300/14 shadow-[0_18px_40px_rgba(34,211,238,0.12)]"
                  : "border-white/12 bg-white/6 hover:border-white/22 hover:bg-white/10"
              }`}
            >
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border ${
                    value === option.value
                      ? "border-cyan-300/30 bg-cyan-300/18 text-cyan-100"
                      : "border-white/12 bg-white/8 text-slate-200"
                  }`}
                >
                  <Icon size={18} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-white">{option.label}</p>
                  <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                    Platform
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {showCustomInput ? (
        <div className="rounded-[28px] border border-white/12 bg-[rgba(10,15,28,0.6)] p-6 backdrop-blur-xl">
          <label
            htmlFor="heardAboutSparkCustom"
            className="text-sm uppercase tracking-[0.24em] text-slate-400"
          >
            Exact source
          </label>
          <input
            id="heardAboutSparkCustom"
            value={customValue}
            onChange={(event) => onCustomValueChange(event.target.value)}
            placeholder="Example: Product Hunt, college group, newsletter"
            className="mt-3 w-full rounded-[24px] border border-white/14 bg-white/8 px-5 py-4 text-base text-white outline-none transition-all placeholder:text-slate-500 focus:border-cyan-300/60 focus:bg-white/12 focus:shadow-[0_0_0_4px_rgba(34,211,238,0.12)]"
          />
          <p className="mt-3 text-sm leading-7 text-slate-400">
            Type the exact place you found Spark so the onboarding summary keeps it visible.
          </p>
        </div>
      ) : null}
    </div>
  );
}
