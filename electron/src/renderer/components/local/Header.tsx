import { useState, useEffect } from "react";
import { X, Minus, Square, Copy, Mic, MicOff, Search } from "lucide-react";
import { useEar } from "@/hooks/useEar";

/** The frameless window's title bar: drag area, the Ctrl+K and mic buttons, window controls. */
export default function Header({ onPalette }: { onPalette?: () => void }) {
  const [isMaximized, setIsMaximized] = useState(false);
  const ear = useEar();

  useEffect(() => {
    void window.electronApi.isMainWindowMaximized().then(setIsMaximized);
    window.electronApi.onWindowMaximizeStateChange(setIsMaximized);
  }, []);

  return (
    <div className="webkit-drag-drag flex h-[34px] w-full shrink-0 items-center justify-between border-b border-[var(--sp-line)] bg-[var(--sp-bg)]">
      <div className="h-full flex-1" />

      <div className="webkit-drag-nodrag flex items-center gap-1.5 px-3">
        {onPalette && (
          <button
            onClick={onPalette}
            className="flex h-[22px] items-center gap-1.5 rounded-md border border-[var(--sp-line-2)] px-2 text-[11px] text-[var(--sp-ink-3)] transition-colors hover:text-[var(--sp-ink)]"
            title="Search everything (Ctrl+K)"
          >
            <Search size={11} strokeWidth={1.8} /> Ctrl K
          </button>
        )}
        <button
          onClick={ear.toggle}
          title={ear.listening ? "Turn the mic off (Ctrl+Shift+M)" : "Turn the mic on (Ctrl+Shift+M)"}
          aria-pressed={ear.listening}
          className={`flex h-[22px] w-[26px] items-center justify-center rounded-md border border-[var(--sp-line-2)] transition-colors ${ear.listening ? "bg-[var(--sp-accent-soft)] text-[var(--sp-accent)]" : "text-[var(--sp-ink-3)]"}`}
        >
          {ear.listening ? <Mic size={12} strokeWidth={1.8} /> : <MicOff size={12} strokeWidth={1.8} />}
        </button>
      </div>

      <div className="webkit-drag-nodrag flex h-full items-center">
        {[
          { action: "MINIMIZE", icon: <Minus size={13} strokeWidth={1.5} />, hover: "hover:bg-white/[0.06]" },
          { action: "MAXIMIZE", icon: isMaximized ? <Copy size={11} strokeWidth={1.5} /> : <Square size={11} strokeWidth={1.5} />, hover: "hover:bg-white/[0.06]" },
          { action: "CLOSE", icon: <X size={13} strokeWidth={1.5} />, hover: "hover:bg-red-700/80" },
        ].map(({ action, icon, hover }) => (
          <button
            key={action}
            onClick={() => window.electronApi.sendFrameAction(action as "MINIMIZE" | "MAXIMIZE" | "CLOSE")}
            className={`flex h-full w-11 items-center justify-center text-[var(--sp-ink-3)] transition-colors ${hover}`}
            aria-label={action.toLowerCase()}
          >
            {icon}
          </button>
        ))}
      </div>
    </div>
  );
}
