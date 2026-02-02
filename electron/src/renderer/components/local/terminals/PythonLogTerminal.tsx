import React, { useState, useEffect, useRef } from 'react';

interface Position {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}


interface DragState {
  x: number;
  y: number;
}

type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw' | null;

interface ParsedLogLine {
  timestamp: string;
  module: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  message: string;
}

export const PythonLogTerminal: React.FC = () => {
    const [logs] = useState<string[]>([
      '2025-12-14 17:39:24,162 - __main__ - INFO - Waiting for commands from Electron...',
      '2025-12-14 17:55:51,238 - __main__ - INFO - Python service started',
      '2025-12-14 17:55:51,239 - __main__ - INFO - Waiting for commands from Electron...',
      '2025-12-14 20:13:20,059 - __main__ - INFO - Python service started',
      '2025-12-14 20:19:38,588 - __main__ - INFO - Handling action: search',
      '2025-12-14 20:21:19,165 - __main__ - INFO - Handling action: open_app',
      '2025-12-14 20:21:22,785 - __main__ - WARNING - Process did not start within 3s',
      '2025-12-14 21:23:20,184 - __main__ - INFO - Python service shutting down'
    ]);
    const scrollRef = useRef<HTMLDivElement>(null);
  
    useEffect(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, [logs]);
  
    const parseLogLine = (line: string): ParsedLogLine | null => {
      const match = line.match(/^([\d\-:\s,]+)\s-\s(.+?)\s-\s(INFO|WARNING|ERROR)\s-\s(.+)$/);
      if (match) {
        return {
          timestamp: match[1],
          module: match[2],
          level: match[3] as ParsedLogLine['level'],
          message: match[4]
        };
      }
      return null;
    };
  
    const getLevelColor = (level: ParsedLogLine['level']): string => {
      const colors: Record<ParsedLogLine['level'], string> = {
        INFO: 'text-cyan-400',
        WARNING: 'text-yellow-400',
        ERROR: 'text-red-400'
      };
      return colors[level];
    };
  
    return (
      <div className="h-full flex flex-col p-3">
        <div className="flex items-center justify-between mb-3 px-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-xs text-emerald-400">python_service.log</span>
          </div>
          <span className="text-xs text-gray-500">{logs.length} lines</span>
        </div>
  
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-2 custom-scrollbar"
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: '#8b5cf6 transparent'
          }}
        >
          <div className="space-y-0.5 font-mono text-[11px]">
            {logs.map((line, index) => {
              const parsed = parseLogLine(line);
              return (
                <div
                  key={index}
                  className="px-2 py-1 rounded hover:bg-white/5 transition-colors"
                >
                  {parsed ? (
                    <div className="flex gap-2">
                      <span className="text-gray-600 shrink-0">{parsed.timestamp}</span>
                      <span className="text-purple-400 shrink-0">{parsed.module}</span>
                      <span className={`font-semibold shrink-0 ${getLevelColor(parsed.level)}`}>
                        {parsed.level}
                      </span>
                      <span className="text-gray-300">{parsed.message}</span>
                    </div>
                  ) : (
                    <span className="text-gray-400">{line}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
  
        <style>{`
          .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
          }
          .custom-scrollbar::-webkit-scrollbar-track {
            background: transparent;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb {
            background: #8b5cf6;
            border-radius: 3px;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background: #a78bfa;
          }
        `}</style>
      </div>
    );
  };
