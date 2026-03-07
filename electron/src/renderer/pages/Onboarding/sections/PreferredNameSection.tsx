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
  eyebrow,
  title,
  description,
  value,
  gender,
  genderOptions,
  onChange,
  onGenderChange,
  onSubmit,
}: PreferredNameSectionProps) {
  return (
    <div className="space-y-7">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-[28px] border border-white/12 bg-[rgba(10,15,28,0.6)] p-6 backdrop-blur-xl">
          <label
            htmlFor="preferredName"
            className="text-sm uppercase tracking-[0.24em] text-slate-400"
          >
            Name
          </label>
          <input
            id="preferredName"
            autoFocus
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                onSubmit();
              }
            }}
            placeholder="Enter the name Spark should use"
            className="mt-3 w-full rounded-[24px] border border-white/14 bg-white/8 px-5 py-4 text-lg text-white outline-none transition-all placeholder:text-slate-500 focus:border-cyan-300/60 focus:bg-white/12 focus:shadow-[0_0_0_4px_rgba(34,211,238,0.12)]"
          />
          <p className="mt-3 text-sm leading-7 text-slate-400">
            Spark will use this as your saved profile name and spoken name for now.
          </p>
        </div>

        <div className="rounded-[28px] border border-white/12 bg-[rgba(10,15,28,0.6)] p-6 backdrop-blur-xl">
          <p className="text-sm uppercase tracking-[0.24em] text-slate-400">
            Profile gender
          </p>
          <div className="mt-4 grid gap-3">
            {genderOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => onGenderChange(option.value)}
                className={`rounded-[20px] border px-4 py-3 text-left transition-all ${
                  gender === option.value
                    ? "border-cyan-300/60 bg-cyan-300/12"
                    : "border-white/10 bg-white/5 hover:border-white/22 hover:bg-white/8"
                }`}
              >
                <p className="text-sm font-semibold text-white">{option.label}</p>
                <p className="mt-1 text-xs leading-6 text-slate-400">
                  {option.description}
                </p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
