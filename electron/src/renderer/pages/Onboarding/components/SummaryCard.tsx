interface SummaryCardProps {
  label: string;
  value: string;
}

export default function SummaryCard({ label, value }: SummaryCardProps) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/15 px-4 py-3">
      <p className="text-[11px] uppercase tracking-[0.24em] text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-sm font-medium text-white">{value}</p>
    </div>
  );
}
