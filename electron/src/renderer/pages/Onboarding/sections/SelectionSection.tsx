import SectionHeader from "../components/SectionHeader";
import type { ChoiceOption } from "../types";

interface SelectionSectionProps {
  eyebrow: string;
  title: string;
  description: string;
  options: ChoiceOption[];
  value: string;
  columns?: "one" | "two" | "three";
  onChange: (value: string) => void;
}

const colsMap = {
  one: "grid gap-2",
  two: "grid gap-2 md:grid-cols-2",
  three: "grid gap-2 md:grid-cols-3",
};

export default function SelectionSection({
  eyebrow, title, description, options, value, columns = "two", onChange,
}: SelectionSectionProps) {
  return (
    <div>
      <SectionHeader eyebrow={eyebrow} title={title} description={description} />

      <div className={colsMap[columns]}>
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            disabled={opt.disabled}
            onClick={() => !opt.disabled && onChange(opt.value)}
            className={`px-4 py-4 rounded-lg text-left transition-colors ${
              opt.disabled ? "opacity-40 cursor-not-allowed " : ""
            }${
              value === opt.value
                ? "bg-white/10 border border-slate-500"
                : "border border-slate-800 hover:border-slate-600"
            }`}
          >
            <p className="text-sm font-medium text-white">{opt.label}</p>
            {opt.description && <p className="text-xs text-slate-500 mt-0.5">{opt.description}</p>}
            {opt.badge && <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{opt.badge}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
