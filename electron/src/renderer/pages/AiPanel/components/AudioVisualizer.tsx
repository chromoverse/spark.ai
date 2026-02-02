import type { AudioVisualizerProps } from '../types';

export function AudioVisualizer({ audioLevel }: AudioVisualizerProps) {
  const bars = 4;

  return (
    <div className="flex items-center gap-0.5 h-7">
      {Array.from({ length: bars }).map((_, i) => {
        const height = Math.max(
          20,
          (audioLevel / 100) * 100 * (0.5 + Math.sin(Date.now() / 200 + i) * 0.5)
        );
        return (
          <div
            key={i}
            className="w-[3px] rounded-sm bg-gradient-to-t from-indigo-500 to-indigo-300 transition-[height] duration-75 ease-out"
            style={{ height: `${height}%` }}
          />
        );
      })}
    </div>
  );
}
