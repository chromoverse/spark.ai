import { memo } from "react";
import { VoiceBubble } from "./VoiceBubble";
import AudioInput from "@/components/local/device/AudioInput"

export const PanelHeader = memo(
  () => {
    return (
      <div className="flex items-center justify-between px-4 h-[52px] border-b border-indigo-300/10">
        {/* Branding */}
        <div className="flex items-center gap-2.5">
          <VoiceBubble/>
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
        <AudioInput isAiPanel={true} />
      </div>
    );
  },
);

PanelHeader.displayName = "PanelHeader";