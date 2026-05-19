import type { ChoiceOption } from "../types";
import SectionHeader from "../components/SectionHeader";

interface PreferredNameSectionProps {
  eyebrow: string;
  title: string;
  description: string;
  value: string;
  gender: string;
  genderOptions: ChoiceOption[];
  onChange: (value: string) => void;
  onGenderChange: (value: string) => void;
  onSubmit: () => void;
}

export default function PreferredNameSection({
  eyebrow, title, description, value, gender, genderOptions, onChange, onGenderChange, onSubmit,
}: PreferredNameSectionProps) {
  const showGender = value.trim().length > 0;

  return (
    <div>
      <SectionHeader eyebrow={eyebrow} title={title} description={description} />

      <input
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onSubmit()}
        placeholder="What should Spark call you?"
        className="w-full px-4 py-3 bg-slate-900/60 border border-slate-700/60 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-slate-500 transition-colors text-lg"
      />

      {showGender && (
        <div className="mt-6">
          <p className="text-xs text-slate-500 mb-2">Gender (optional)</p>
          <div className="flex gap-2">
            {genderOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onGenderChange(opt.value)}
                className={`px-4 py-2 rounded-md text-sm transition-colors ${
                  gender === opt.value
                    ? "bg-white/10 text-white border border-slate-500"
                    : "text-slate-400 border border-slate-800 hover:border-slate-600 hover:text-slate-300"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
