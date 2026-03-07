interface OptionTileProps {
  active: boolean;
  label: string;
  description: string;
  badge?: string;
  disabled?: boolean;
  onClick: () => void;
}

export default function OptionTile({
  active,
  label,
  description,
  badge,
  disabled = false,
  onClick,
}: OptionTileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[24px] border p-5 text-left transition-all duration-300 ${
        active
          ? "border-cyan-300/70 bg-white/14 shadow-[0_16px_48px_rgba(34,211,238,0.16)]"
          : disabled
            ? "cursor-not-allowed border-white/8 bg-white/[0.04] opacity-65"
            : "border-white/12 bg-white/6 hover:border-white/24 hover:bg-white/10"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-lg font-semibold text-white">{label}</p>
        {badge ? (
          <span className="rounded-full border border-amber-300/30 bg-amber-300/12 px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-amber-100">
            {badge}
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-300">{description}</p>
    </button>
  );
}
