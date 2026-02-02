import { memo } from "react";
import type { PanelHeaderProps } from "../types";
import { VoiceBubble } from "./VoiceBubble";
import { AudioVisualizer } from "./AudioVisualizer";

export const PanelHeader = memo(
  ({ audioLevel }: PanelHeaderProps) => {
    return (
      <div className="flex items-center justify-between px-4 h-[52px] border-b border-indigo-300/10">
        {/* Branding */}
        <div className="flex items-center gap-2.5">
          <VoiceBubble audioLevel={audioLevel} />
          <div className="flex flex-col gap-0.5">
            <span className="text-indigo-100 font-semibold text-[13px] leading-none">
              Spark
            </span>
            <span className="text-indigo-200/60 text-[11px] leading-none">
              AI Assistant
            </span>
          </div>
        </div>
        {/* Visualizer */}
        <AudioVisualizer audioLevel={audioLevel} />
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Only re-render if audioLevel changes significantly (reduce visual jitter)
    return Math.abs(prevProps.audioLevel - nextProps.audioLevel) < 5;
  },
);

PanelHeader.displayName = "PanelHeader";
