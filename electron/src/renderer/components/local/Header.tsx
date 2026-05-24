import { useState, useEffect } from "react";
import { X, Minus, Square, Copy, Mic, MicOff } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { toggleMicrophoneListening } from "@/store/features/localState/localSlice";

export default function Header() {
  const dispatch = useAppDispatch();
  const [isMaximized, setIsMaximized] = useState(false);
  const { isMicrophoneListening } = useAppSelector((s) => s.localState);

  useEffect(() => {
    (async () => {
      setIsMaximized(await window.electronApi.isMainWindowMaximized());
    })();
    window.electronApi.onWindowMaximizeStateChange(setIsMaximized);
  }, []);

  return (
    <div
      className="webkit-drag-drag w-full flex items-center justify-between shrink-0"
      style={{
        height: 34,
        background: "var(--sp-bg)",
        borderBottom: "1px solid var(--sp-line)",
      }}
    >
      {/* Left — drag region */}
      <div className="flex-1 h-full" />

      {/* Centre — mic toggle */}
      <div className="webkit-drag-nodrag flex items-center gap-1 px-3">
        <button
          onClick={() => dispatch(toggleMicrophoneListening())}
          title={isMicrophoneListening ? "Mute" : "Unmute"}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 26,
            height: 22,
            borderRadius: 5,
            border: "1px solid var(--sp-line-2)",
            background: isMicrophoneListening ? "var(--sp-accent-soft)" : "transparent",
            color: isMicrophoneListening ? "var(--sp-accent)" : "var(--sp-ink-3)",
            cursor: "pointer",
            transition: "all 120ms",
          }}
        >
          {isMicrophoneListening
            ? <Mic size={12} strokeWidth={1.8} />
            : <MicOff size={12} strokeWidth={1.8} />}
        </button>
      </div>

      {/* Right — window controls */}
      <div className="webkit-drag-nodrag flex items-center h-full">
        {[
          { action: "MINIMIZE", icon: <Minus size={13} strokeWidth={1.5} />, hover: "hover:bg-[#2a2822]" },
          {
            action: "MAXIMIZE",
            icon: isMaximized ? <Copy size={11} strokeWidth={1.5} /> : <Square size={11} strokeWidth={1.5} />,
            hover: "hover:bg-[#2a2822]",
          },
          { action: "CLOSE", icon: <X size={13} strokeWidth={1.5} />, hover: "hover:bg-red-700/80" },
        ].map(({ action, icon, hover }) => (
          <button
            key={action}
            onClick={() => window.electronApi.sendFrameAction(action as "MINIMIZE" | "MAXIMIZE" | "CLOSE")}
            className={`flex items-center justify-center w-11 h-full transition-colors ${hover}`}
            style={{ color: "var(--sp-ink-3)" }}
          >
            {icon}
          </button>
        ))}
      </div>
    </div>
  );
}
