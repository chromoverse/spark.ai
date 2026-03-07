import { X, Minus, Square, Copy } from "lucide-react";
import React, { useEffect, useState } from "react";

interface Props {
  removeMinimize?: boolean;
  removeMaximize?: boolean;
}

export default function MinimalHeader({ removeMinimize = false, removeMaximize = false }: Props) {
  const [isMainWindowMaximized, setIsMainWindowMaximized] =
    useState<boolean>(false);

  useEffect(() => {
    (async () => {
      const isMax = await window.electronApi.isMainWindowMaximized();
      setIsMainWindowMaximized(isMax);
    })();

    // continuis listen wndow frame state change
    window.electronApi.onWindowMaximizeStateChange((isMainWinMaximized) => {
      setIsMainWindowMaximized(isMainWinMaximized);
    });
  }, []);

  console.log("Frame State main", isMainWindowMaximized);

  return (
    <div className="w-full min-h-10 webkit-drag-drag flex justify-end items-center text-white">
      {/* Right Section */}
      <div className="flex items-center justify-center gap-0 webkit-drag-nodrag">
        {!removeMinimize && (
          <ul
            onClick={() => window.electronApi.sendFrameAction("MINIMIZE")}
            className="hover:bg-white/10 h-full flex items-center justify-center mx-3"
          >
            <Minus strokeWidth={0.75} size={16} />
          </ul>
        )}
        {!removeMaximize && (
          <ul
            onClick={() => window.electronApi.sendFrameAction("MAXIMIZE")}
            className="hover:bg-white/10 h-full flex items-center justify-center mx-3 "
          >
            {isMainWindowMaximized ? (
              <Copy strokeWidth={0.75} size={11} />
            ) : (
              <Square strokeWidth={0.75} size={11} />
            )}
          </ul>
        )}
        <ul
          onClick={() => window.electronApi.sendFrameAction("CLOSE")}
          className="hover:bg-red-500 h-full flex items-center justify-center mx-3"
        >
          <X strokeWidth={0.55} size={16} />
        </ul>
      </div>
    </div>
  );
}
