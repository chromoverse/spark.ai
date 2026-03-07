interface SectionHeaderProps {
  eyebrow: string;
  title: string;
  description: string;
}

export default function SectionHeader({
  eyebrow,
  title,
  description,
}: SectionHeaderProps) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.26em] text-cyan-100/80">
        {eyebrow}
      </p>
      <h2 className="mt-4 text-4xl font-semibold tracking-tight text-white md:text-5xl">
        {title}
      </h2>
      <p className="mt-4 max-w-3xl text-base leading-7 text-slate-300">
        {description}
      </p>
    </div>
  );
}
