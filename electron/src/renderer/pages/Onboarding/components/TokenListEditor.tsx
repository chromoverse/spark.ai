import { Plus } from "lucide-react";
import { countFilledTokens } from "../utils";

interface TokenListEditorProps {
  providerLabel: string;
  values: string[];
  minimumRequired: number;
  optional?: boolean;
  onChange: (values: string[]) => void;
}

export default function TokenListEditor({
  providerLabel,
  values,
  minimumRequired,
  optional = false,
  onChange,
}: TokenListEditorProps) {
  const activeCount = countFilledTokens(values);

  const updateValue = (index: number, nextValue: string) => {
    onChange(
      values.map((value, valueIndex) =>
        valueIndex === index ? nextValue : value,
      ),
    );
  };

  const addTokenRow = () => {
    onChange([...values, ""]);
  };

  const clearTokens = () => {
    onChange(values.map(() => ""));
  };

  return (
    <div className="rounded-[28px] border border-white/12 bg-[rgba(10,15,28,0.58)] p-6 backdrop-blur-xl">
      <div className="flex flex-col gap-3 border-b border-white/10 pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-lg font-semibold text-white">{providerLabel}</h3>
            <span
              className={`rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.2em] ${
                optional
                  ? "border-white/12 bg-white/6 text-slate-300"
                  : activeCount >= minimumRequired
                    ? "border-emerald-300/30 bg-emerald-300/12 text-emerald-100"
                    : "border-amber-300/30 bg-amber-300/12 text-amber-100"
              }`}
            >
              {optional
                ? "Optional fallback"
                : `Required: ${minimumRequired} key${minimumRequired > 1 ? "s" : ""}`}
            </span>
          </div>
          <p className="mt-1 text-sm leading-7 text-slate-300">
            {optional
              ? "Keep this list tidy. Blank rows stay local and are ignored when you save."
              : `Add at least ${minimumRequired} key${minimumRequired > 1 ? "s" : ""}. Blank rows stay local and are ignored when you save.`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={clearTokens}
            className="rounded-full border border-white/12 px-4 py-2 text-sm font-medium text-slate-200 transition-all hover:border-white/24 hover:bg-white/10"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={addTokenRow}
            className="inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-sm font-medium text-cyan-100 transition-all hover:border-cyan-300/50 hover:bg-cyan-300/16"
          >
            <Plus size={14} />
            Add token
          </button>
        </div>
      </div>

      {!optional ? (
        <div className="mt-4 rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-sm text-slate-300">
          {activeCount >= minimumRequired
            ? `${activeCount} key${activeCount > 1 ? "s" : ""} ready.`
            : `${minimumRequired - activeCount} more key${minimumRequired - activeCount > 1 ? "s" : ""} needed before you can continue.`}
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {values.map((value, index) => (
          <div
            key={`${providerLabel}-${index}`}
            className="rounded-[22px] border border-white/10 bg-white/6 p-4"
          >
            <div className="mb-2 flex items-center justify-between gap-3">
              <label
                htmlFor={`${providerLabel}-${index}`}
                className="text-[11px] uppercase tracking-[0.22em] text-slate-400"
              >
                Token {index + 1}
              </label>
              <span className="rounded-full border border-white/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                Secure field
              </span>
            </div>
            <input
              id={`${providerLabel}-${index}`}
              type="password"
              value={value}
              onChange={(event) => updateValue(index, event.target.value)}
              placeholder={`Paste ${providerLabel} token ${index + 1}`}
              className="w-full rounded-[18px] border border-white/12 bg-black/20 px-4 py-3.5 text-sm text-white outline-none transition-all placeholder:text-slate-500 focus:border-cyan-300/60 focus:bg-white/10 focus:shadow-[0_0_0_4px_rgba(34,211,238,0.12)]"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
