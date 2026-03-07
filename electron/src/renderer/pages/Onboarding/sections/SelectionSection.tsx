import OptionTile from "../components/OptionTile";
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

const columnsMap = {
  one: "grid gap-4",
  two: "grid gap-4 md:grid-cols-2",
  three: "grid gap-4 md:grid-cols-3",
};

export default function SelectionSection({
  eyebrow,
  title,
  description,
  options,
  value,
  columns = "two",
  onChange,
}: SelectionSectionProps) {
  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className={columnsMap[columns]}>
        {options.map((option) => (
          <OptionTile
            key={option.value}
            active={value === option.value}
            label={option.label}
            description={option.description}
            badge={option.badge}
            disabled={option.disabled}
            onClick={() => {
              if (!option.disabled) {
                onChange(option.value);
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}
