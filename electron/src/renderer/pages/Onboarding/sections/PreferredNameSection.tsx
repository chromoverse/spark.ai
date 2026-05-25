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
        className="w-full px-4 py-3 bg-[#0f0f16] border border-white/10 rounded-lg text-white placeholder-white/20 focus:outline-none focus:border-[#d97757] transition-colors text-lg"
      />

      {showGender && (
        <div className="mt-6">
          <p className="text-xs text-white/30 mb-2">Gender (optional)</p>
          <div className="flex gap-2">
            {genderOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onGenderChange(opt.value)}
                className={`px-4 py-2 rounded-md text-sm transition-colors ${
                  gender === opt.value
                    ? "bg-white/10 text-white border border-[#d97757]/50"
                    : "text-white/40 border border-white/8 hover:border-white/20 hover:text-white/70"
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
