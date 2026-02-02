import React, { useEffect, useRef } from "react";
import { useSocket } from "@/context/socketContextProvider";
import type { ServerStatus } from "@shared/socket.types";
import { formatDate, formatTime } from "@/utils/date";
import { Info } from "lucide-react";

export const dummyServerStatus: ServerStatus[] = [
  {
    flag: "INFO",
    status: "Backend Fired Up",
    timestamp: "2025-12-14T14:13:02.114392+00:00",
  },
  {
    flag: "INFO",
    status: "Analyzing your data",
    timestamp: "2025-12-14T14:13:02.241901+00:00",
  },
  {
    flag: "INFO",
    status: "TTS Request Received",
    timestamp: "2025-12-14T14:15:11.441209+00:00",
  },
  {
    flag: "INFO",
    status: "Loaded user preferences as gender=female, language=hi",
    timestamp: "2025-12-14T14:15:11.672113+00:00",
  },
  {
    flag: "INFO",
    status: "TTS generation completed successfully",
    timestamp: "2025-12-14T14:15:12.889342+00:00",
  },
  {
    flag: "INFO",
    status: "Analyzing your data",
    timestamp: "2025-12-14T14:13:02.241901+00:00",
  },
  {
    flag: "INFO",
    status: "TTS Request Received",
    timestamp: "2025-12-14T14:15:11.441209+00:00",
  },
  {
    flag: "INFO",
    status: "Loaded user preferences as gender=female, language=hi",
    timestamp: "2025-12-14T14:15:11.672113+00:00",
  },
  {
    flag: "INFO",
    status: "TTS generation completed successfully",
    timestamp: "2025-12-14T14:15:12.889342+00:00",
  },
  {
    flag: "INFO",
    status: "Analyzing your data",
    timestamp: "2025-12-14T14:13:02.241901+00:00",
  },
  {
    flag: "INFO",
    status: "TTS Request Received",
    timestamp: "2025-12-14T14:15:11.441209+00:00",
  },
  {
    flag: "INFO",
    status: "Loaded user preferences as gender=female, language=hi",
    timestamp: "2025-12-14T14:15:11.672113+00:00",
  },
  {
    flag: "INFO",
    status: "TTS generation completed successfully",
    timestamp: "2025-12-14T14:15:12.889342+00:00",
  },
  {
    flag: "WARN",
    status: "High response latency detected",
    timestamp: "2025-12-14T14:18:45.932118+00:00",
  },
  {
    flag: "ERROR",
    status: "TTS worker crashed unexpectedly",
    timestamp: "2025-12-14T14:21:09.001883+00:00",
  },
];

const flagStyles = {
  INFO: "text-blue-400",
  WARN: "text-yellow-400",
  ERROR: "text-red-400",
};

function ServerStatusShower() {
  const [statusArr, setStatusArr] = React.useState<ServerStatus[]>([]);
  const [order, setOrder] = React.useState<"asc" | "desc">("desc");
  const { isConnected, socket, on } = useSocket();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isConnected || !socket) return;
    const handleServerStatus = (data: ServerStatus) => {
      setStatusArr((prev) => [...prev, data]);
    };
    on("server-status", handleServerStatus);

    return () => {
      socket.off("server-status", handleServerStatus);
    };
  }, [isConnected, socket, on]);

  // Auto-scroll to bottom when new logs arrive (only in desc mode)
  useEffect(() => {
    if (scrollRef.current && order === "desc") {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [statusArr, order]);

  const displayedLogs = order === "desc" ? [...statusArr].reverse() : statusArr;

  return (
    <div className="h-[80vh] overflow-hidden rounded-xl border border-neutral-800 bg-neutral-950 p-4 text-sm">
       <div className="flex items-center justify-between mb-3 px-2">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs text-cyan-400">LIVE</span>
        </div>
        
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Sort:</span>
          <button
            onClick={() => setOrder('asc')}
            type="button"
            className={`px-2 py-1 text-xs rounded transition-all ${
              order === 'asc'
                ? 'bg-purple-600/30 text-purple-300 border border-purple-500/50'
                : 'bg-gray-800/30 text-gray-400 hover:bg-gray-700/30'
            }`}
          >
            ↑ ASC
          </button>
          <button
            onClick={() => setOrder('desc')}
            type="button"
            className={`px-2 py-1 text-xs rounded transition-all ${
              order === 'desc'
                ? 'bg-purple-600/30 text-purple-300 border border-purple-500/50'
                : 'bg-gray-800/30 text-gray-400 hover:bg-gray-700/30'
            }`}
          >
            ↓ DESC
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="h-[calc(100%-3rem)] overflow-y-auto pr-2"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: "#404040 transparent",
        }}
      >
        <style>{`
          .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
          }
          .custom-scrollbar::-webkit-scrollbar-track {
            background: transparent;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb {
            background: #404040;
            border-radius: 3px;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background: #525252;
          }
        `}</style>

        <ul className="space-y-2 custom-scrollbar">
          {displayedLogs.map((log, index) => (
            <li
              key={index}
              className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-neutral-900"
            >
              {/* Left Time */}
              <span className="w-20 shrink-0 text-neutral-400">
                [{formatTime(log.timestamp)}]
              </span>

              {/* Info Hover */}
              <div className="group relative">
                <Info size={14} className="text-neutral-500" />
                <div className="absolute left-1/2 top-6 z-10 hidden -translate-x-1/2 rounded-md bg-black px-2 py-1 text-xs text-neutral-200 shadow-md group-hover:block whitespace-nowrap">
                  {formatDate(log.timestamp)}
                </div>
              </div>

              {/* Flag */}
              <span className={`w-[60px] font-medium ${flagStyles[log.flag]}`}>
                {log.flag}
              </span>

              {/* Message */}
              <span className="text-neutral-200">{log.status}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default ServerStatusShower;
