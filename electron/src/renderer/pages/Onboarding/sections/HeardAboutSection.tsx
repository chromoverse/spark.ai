import {
  Github, Globe, Instagram, Linkedin, MessageCircle, MessageSquare, Twitter, Users, Youtube,
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

const iconMap: Record<string, typeof Globe> = {
  youtube: Youtube, instagram: Instagram, twitter: Twitter, linkedin: Linkedin,
  github: Github, users: Users, globe: Globe, reddit: MessageCircle, discord: MessageSquare,
};

export default function HeardAboutSection({
  eyebrow, title, description, options, value, customValue, onChange, onCustomValueChange,
}: HeardAboutSectionProps) {
  return (
    <div>
      <SectionHeader eyebrow={eyebrow} title={title} description={description} />

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">
        {options.map((opt) => {
          const Icon = iconMap[opt.iconKey ?? "globe"] ?? Globe;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={`flex items-center gap-3 px-4 py-4 rounded-lg text-left text-sm transition-colors ${
                value === opt.value
                  ? "bg-white/10 border border-slate-500 text-white"
                  : "text-slate-400 border border-slate-800 hover:border-slate-600 hover:text-slate-300"
              }`}
            >
              <Icon size={16} className="shrink-0 text-slate-400" />
              <span>{opt.label}</span>
            </button>
          );
        })}
      </div>

      {value === "other" && (
        <div className="mt-4">
          <input
            value={customValue}
            onChange={(e) => onCustomValueChange(e.target.value)}
            placeholder="Where did you find Spark?"
            className="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
      )}
    </div>
  );
}
