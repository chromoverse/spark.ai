import { X, Minus, Square, Copy } from "lucide-react";
import React, { useEffect, useState } from "react";

export default function MinimalHeader() {
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
    <div className="w-full min-h-8 bg-white/5 webkit-drag-drag flex justify-end items-center text-white">
      {/* Right Section */}
      <div className="flex items-center justify-center gap-0 h-10 webkit-drag-nodrag">
        <ul
          onClick={() => window.electronApi.sendFrameAction("MINIMIZE")}
          className="hover:bg-white/10 h-full flex items-center justify-center w-12"
        >
          <Minus strokeWidth={0.75} size={20} />
        </ul>
        <ul
          onClick={() => window.electronApi.sendFrameAction("MAXIMIZE")}
          className="hover:bg-white/10 h-full flex items-center justify-center w-12"
        >
          {isMainWindowMaximized ? (
            <Copy strokeWidth={0.75} size={15} />
          ) : (
            <Square strokeWidth={0.75} size={15} />
          )}
        </ul>
        <ul
          onClick={() => window.electronApi.sendFrameAction("CLOSE")}
          className="hover:bg-red-500 h-full flex items-center justify-center w-12"
        >
          <X strokeWidth={0.75} size={20} />
        </ul>
      </div>
    </div>
  );
}
