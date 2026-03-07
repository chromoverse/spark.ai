import { Play } from "lucide-react";
import type { VoiceCatalogEntry } from "../types";

interface VoiceCardProps {
  voice: VoiceCatalogEntry;
  active: boolean;
  onSelect: () => void;
  onPreview: () => void;
  isPreviewing: boolean;
  visualizerBars: number[];
}

function MiniVisualizer({ bars }: { bars: number[] }) {
  return (
    <div className="flex h-8 items-end gap-1.5 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-2">
      {bars.map((bar, index) => (
        <span
          key={`bar-${index}`}
          className="w-1 rounded-full bg-cyan-100 transition-all duration-150"
          style={{
            height: `${Math.max(bar, 18)}%`,
            opacity: 0.45 + bar / 140,
          }}
        />
      ))}
    </div>
  );
}

export default function VoiceCard({
  voice,
  active,
  onSelect,
  onPreview,
  isPreviewing,
  visualizerBars,
}: VoiceCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className={`rounded-[24px] border p-4 transition-all duration-300 ${
        active
          ? "border-cyan-300/70 bg-white/14 shadow-[0_16px_42px_rgba(34,211,238,0.16)]"
          : "cursor-pointer border-white/12 bg-white/6 hover:border-white/22 hover:bg-white/8"
      }`}
    >
      <div className="flex items-start gap-4">
        {voice.iconUrl ? (
          <img
            src={voice.iconUrl}
            alt={voice.name}
            className="h-14 w-14 rounded-2xl border border-white/10 bg-white/8 object-cover"
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="truncate text-base font-semibold text-white">{voice.name}</p>
              <p className="mt-1 text-[11px] uppercase tracking-[0.22em] text-slate-400">
                {voice.gender} voice
              </p>
            </div>
            <div
              className={`mt-0.5 flex h-7 min-w-7 items-center justify-center rounded-full border ${
                active
                  ? "border-cyan-300/50 bg-cyan-300/18 text-cyan-100"
                  : "border-white/10 text-slate-400"
              }`}
            >
              <span className="h-2.5 w-2.5 rounded-full bg-current" />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onPreview();
          }}
          className="inline-flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1.5 text-[11px] font-medium text-slate-200 transition-all hover:border-white/24 hover:bg-white/10"
        >
          <Play size={11} />
          {isPreviewing ? "Playing sample" : "Preview sample"}
        </button>

        {isPreviewing && visualizerBars.length > 0 ? (
          <MiniVisualizer bars={visualizerBars} />
        ) : null}
      </div>
    </div>
  );
}
