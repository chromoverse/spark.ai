import React, { useState, useEffect, useRef } from 'react';
import { Info, Maximize2, Minimize2, RotateCcw, Terminal, FileText } from 'lucide-react';

// ============================================================================
// TYPE DEFINITIONS
// ============================================================================

interface Position {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

interface Terminal {
  id: string;
  zIndex: number;
}

interface DragState {
  x: number;
  y: number;
}

interface ResizeState extends DragState {
  width: number;
  height: number;
  posX: number;
  posY: number;
}

type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw' | null;

interface DraggableTerminalProps {
  id: string;
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  children: React.ReactNode;
  initialPosition?: Position;
  initialSize?: Size;
  zIndex?: number;
  onFocus?: () => void;
}

interface ResizeHandleProps {
  direction: ResizeDirection;
  className: string;
  style?: React.CSSProperties;
}

interface ServerLog {
  timestamp: string;
  flag: 'INFO' | 'WARN' | 'ERROR';
  status: string;
}

interface ParsedLogLine {
  timestamp: string;
  module: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  message: string;
}

// ============================================================================
// DRAGGABLE TERMINAL COMPONENT
// ============================================================================

export const DraggableTerminal: React.FC<DraggableTerminalProps> = ({ 
  id,
  title, 
  icon: Icon, 
  children, 
  initialPosition = { x: 50, y: 50 },
  initialSize = { width: 600, height: 400 },
  zIndex = 10,
  onFocus = () => {}
}) => {
  const [position, setPosition] = useState<Position>(initialPosition);
  const [size, setSize] = useState<Size>(initialSize);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [isResizing, setIsResizing] = useState<boolean>(false);
  const [resizeDirection, setResizeDirection] = useState<ResizeDirection>(null);
  const [dragStart, setDragStart] = useState<DragState>({ x: 0, y: 0 });
  const [resizeStart, setResizeStart] = useState<ResizeState>({ x: 0, y: 0, width: 0, height: 0, posX: 0, posY: 0 });
  const [isMinimized, setIsMinimized] = useState<boolean>(false);
  const [hoverEdge, setHoverEdge] = useState<ResizeDirection>(null);
  const terminalRef = useRef<HTMLDivElement>(null);

  const originalState = useRef<{ position: Position; size: Size }>({ 
    position: initialPosition, 
    size: initialSize 
  });

  const handleClick = (): void => {
    onFocus();
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent): void => {
      if (isDragging) {
        const newX = e.clientX - dragStart.x;
        const newY = e.clientY - dragStart.y;
        
        const maxX = window.innerWidth - size.width;
        const maxY = window.innerHeight - (isMinimized ? 48 : size.height);
        
        setPosition({
          x: Math.max(0, Math.min(maxX, newX)),
          y: Math.max(0, Math.min(maxY, newY))
        });
      }
      
      if (isResizing && resizeDirection) {
        const deltaX = e.clientX - resizeStart.x;
        const deltaY = e.clientY - resizeStart.y;
        
        let newWidth = resizeStart.width;
        let newHeight = resizeStart.height;
        let newX = resizeStart.posX;
        let newY = resizeStart.posY;

        if (resizeDirection.includes('e')) {
          newWidth = Math.max(300, Math.min(window.innerWidth - newX, resizeStart.width + deltaX));
        }
        if (resizeDirection.includes('s')) {
          newHeight = Math.max(200, Math.min(window.innerHeight - newY, resizeStart.height + deltaY));
        }
        if (resizeDirection.includes('w')) {
          const potentialWidth = resizeStart.width - deltaX;
          const potentialX = resizeStart.posX + deltaX;
          
          if (potentialWidth >= 300 && potentialX >= 0) {
            newWidth = potentialWidth;
            newX = potentialX;
          }
        }
        if (resizeDirection.includes('n')) {
          const potentialHeight = resizeStart.height - deltaY;
          const potentialY = resizeStart.posY + deltaY;
          
          if (potentialHeight >= 200 && potentialY >= 0) {
            newHeight = potentialHeight;
            newY = potentialY;
          }
        }

        if (newX + newWidth > window.innerWidth) {
          newWidth = window.innerWidth - newX;
        }
        if (newY + newHeight > window.innerHeight) {
          newHeight = window.innerHeight - newY;
        }

        setSize({ width: newWidth, height: newHeight });
        setPosition({ x: newX, y: newY });
      }
    };

    const handleMouseUp = (): void => {
      setIsDragging(false);
      setIsResizing(false);
      setResizeDirection(null);
    };

    if (isDragging || isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = isDragging ? 'grabbing' : getResizeCursor(resizeDirection);
      document.body.style.userSelect = 'none';
    } else {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, isResizing, dragStart, resizeStart, position, size, resizeDirection, isMinimized]);

  useEffect(() => {
    const handleResize = (): void => {
      const maxX = window.innerWidth - size.width;
      const maxY = window.innerHeight - size.height;
      
      setPosition(prev => ({
        x: Math.max(0, Math.min(maxX, prev.x)),
        y: Math.max(0, Math.min(maxY, prev.y))
      }));
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [size]);

  const getResizeCursor = (direction: ResizeDirection): string => {
    if (!direction) return '';
    if (direction === 'e' || direction === 'w') return 'ew-resize';
    if (direction === 'n' || direction === 's') return 'ns-resize';
    if (direction === 'ne' || direction === 'sw') return 'nesw-resize';
    if (direction === 'nw' || direction === 'se') return 'nwse-resize';
    return '';
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
    const target = e.target as HTMLElement;
    if (target.closest('.terminal-header') && !target.closest('button')) {
      e.preventDefault();
      setIsDragging(true);
      setDragStart({
        x: e.clientX - position.x,
        y: e.clientY - position.y
      });
    }
  };

  const handleResizeStart = (e: React.MouseEvent<HTMLDivElement>, direction: ResizeDirection): void => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    setResizeDirection(direction);
    setResizeStart({
      x: e.clientX,
      y: e.clientY,
      width: size.width,
      height: size.height,
      posX: position.x,
      posY: position.y
    });
  };

  const handleMouseEnter = (direction: ResizeDirection): void => {
    if (!isDragging && !isResizing) {
      setHoverEdge(direction);
    }
  };

  const handleMouseLeave = (): void => {
    if (!isResizing) {
      setHoverEdge(null);
    }
  };

  const resetToOriginalSize = (e: React.MouseEvent<HTMLButtonElement>): void => {
    e.stopPropagation();
    setPosition(originalState.current.position);
    setSize(originalState.current.size);
  };

  const ResizeHandle: React.FC<ResizeHandleProps & { direction: ResizeDirection }> = ({ 
    direction, 
    className, 
    style 
  }) => (
    <div
      onMouseDown={(e) => handleResizeStart(e, direction)}
      onMouseEnter={() => handleMouseEnter(direction)}
      onMouseLeave={handleMouseLeave}
      className={`absolute ${className} transition-opacity duration-150 ${
        hoverEdge === direction ? 'opacity-100' : 'opacity-0'
      } hover:opacity-100`}
      style={{
        ...style,
        cursor: getResizeCursor(direction),
        zIndex: 20
      }}
    >
      <div className={`w-full h-full ${
        hoverEdge === direction || isResizing && resizeDirection === direction
          ? 'bg-linear-to-r from-cyan-500/50 to-purple-500/50'
          : 'bg-purple-500/30'
      } transition-all duration-200`} />
    </div>
  );

  return (
    <div
      ref={terminalRef}
      onClick={handleClick}
      className={`absolute rounded-xl overflow-hidden transition-shadow duration-200 select-none ${
        isDragging ? 'shadow-2xl shadow-cyan-500/50' : 'shadow-xl'
      } ${isMinimized ? 'h-12' : ''}`}
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: isMinimized ? '300px' : `${size.width}px`,
        height: isMinimized ? '48px' : `${size.height}px`,
        background: 'linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%)',
        border: '1px solid rgba(139, 92, 246, 0.3)',
        zIndex: isDragging ? 1000 : zIndex
      }}
    >
      {isDragging && (
        <div 
          className="absolute inset-0 pointer-events-none"
          style={{
            background: 'radial-gradient(circle at center, rgba(34, 211, 238, 0.3), rgba(139, 92, 246, 0.2) 50%, transparent 70%)',
            animation: 'meteorPulse 0.8s ease-in-out infinite',
            filter: 'blur(20px)'
          }}
        />
      )}

      {!isMinimized && (
        <>
          <ResizeHandle direction="n" className="top-0 left-0 right-0 h-1" />
          <ResizeHandle direction="s" className="bottom-0 left-0 right-0 h-1" />
          <ResizeHandle direction="e" className="top-0 bottom-0 right-0 w-1" />
          <ResizeHandle direction="w" className="top-0 bottom-0 left-0 w-1" />
          <ResizeHandle direction="nw" className="top-0 left-0 w-3 h-3" style={{ cursor: 'nwse-resize' }} />
          <ResizeHandle direction="ne" className="top-0 right-0 w-3 h-3" style={{ cursor: 'nesw-resize' }} />
          <ResizeHandle direction="sw" className="bottom-0 left-0 w-3 h-3" style={{ cursor: 'nesw-resize' }} />
          <ResizeHandle direction="se" className="bottom-0 right-0 w-3 h-3" style={{ cursor: 'nwse-resize' }} />
        </>
      )}

      <div
        className="terminal-header flex items-center justify-between px-4 py-2 cursor-grab active:cursor-grabbing select-none"
        style={{
          background: 'linear-gradient(90deg, rgba(139, 92, 246, 0.15), rgba(34, 211, 238, 0.15))',
          borderBottom: '1px solid rgba(139, 92, 246, 0.2)'
        }}
        onMouseDown={handleMouseDown}
      >
        <div className="flex items-center gap-2 pointer-events-none">
          <Icon size={16} className="text-cyan-400" />
          <span className="text-sm font-semibold text-cyan-300">{title}</span>
        </div>
        
        <div className="flex items-center gap-1 pointer-events-auto">
          <button
            onClick={resetToOriginalSize}
            className="p-1 hover:bg-white/10 rounded transition-colors group"
            title="Reset to original size"
            type="button"
          >
            <RotateCcw size={14} className="text-emerald-400 group-hover:rotate-180 transition-transform duration-300" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIsMinimized(!isMinimized);
            }}
            className="p-1 hover:bg-white/10 rounded transition-colors"
            title={isMinimized ? "Maximize" : "Minimize"}
            type="button"
          >
            {isMinimized ? (
              <Maximize2 size={14} className="text-purple-400" />
            ) : (
              <Minimize2 size={14} className="text-purple-400" />
            )}
          </button>
        </div>
      </div>

      {!isMinimized && (
        <div className="h-[calc(100%-40px)] overflow-hidden">
          {children}
        </div>
      )}

      <style>{`
        @keyframes meteorPulse {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.05); }
        }
      `}</style>
    </div>
  );
};

const ServerStatusTerminal: React.FC = () => {
  const [statusArr, setStatusArr] = useState<ServerLog[]>([
    { timestamp: new Date().toISOString(), flag: 'INFO', status: 'Server logs will appear here...' },
    { timestamp: new Date(Date.now() - 5000).toISOString(), flag: 'WARN', status: 'Waiting for socket connection' },
    { timestamp: new Date(Date.now() - 10000).toISOString(), flag: 'INFO', status: 'System initialized' }
  ]);
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current && order === 'desc') {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [statusArr, order]);

  const displayedLogs: ServerLog[] = order === 'desc' ? [...statusArr].reverse() : statusArr;

  const flagStyles: Record<ServerLog['flag'], string> = {
    INFO: 'text-cyan-400',
    WARN: 'text-yellow-400',
    ERROR: 'text-red-400'
  };

  const formatTime = (timestamp: string): string => {
    return new Date(timestamp).toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit' 
    });
  };

  const formatDate = (timestamp: string): string => {
    return new Date(timestamp).toLocaleString();
  };

  return (
    <div className="h-full flex flex-col p-3">
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
        className="flex-1 overflow-y-auto px-2 custom-scrollbar"
        style={{
          scrollbarWidth: 'thin',
          scrollbarColor: '#8b5cf6 transparent'
        }}
      >
        <ul className="space-y-1 font-mono text-xs">
          {displayedLogs.map((log, index) => (
            <li
              key={index}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/5 transition-colors group"
            >
              <span className="text-gray-500 shrink-0 w-16">
                {formatTime(log.timestamp)}
              </span>

              <div className="relative group/info">
                <Info size={12} className="text-gray-600 group-hover/info:text-cyan-400 transition-colors" />
                <div className="absolute left-1/2 top-6 z-50 hidden group-hover/info:block -translate-x-1/2 bg-black/90 px-2 py-1 text-[10px] text-gray-300 rounded whitespace-nowrap border border-purple-500/30">
                  {formatDate(log.timestamp)}
                </div>
              </div>

              <span className={`font-semibold w-12 shrink-0 ${flagStyles[log.flag]}`}>
                {log.flag}
              </span>

              <span className="text-gray-300">{log.status}</span>
            </li>
          ))}
        </ul>
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

// ============================================================================
// PYTHON LOG TERMINAL
// ============================================================================

const PythonLogTerminal: React.FC = () => {
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

// ============================================================================
// MAIN APP COMPONENT
// ============================================================================

const App: React.FC = () => {
  const [terminals, setTerminals] = useState<Terminal[]>([
    { id: 'server-status', zIndex: 10 },
    { id: 'python-logs', zIndex: 11 }
  ]);

  const bringToFront = (id: string): void => {
    setTerminals(prev => {
      const maxZ = Math.max(...prev.map(t => t.zIndex));
      return prev.map(t => 
        t.id === id ? { ...t, zIndex: maxZ + 1 } : t
      );
    });
  };

  const getZIndex = (id: string): number => {
    return terminals.find(t => t.id === id)?.zIndex || 10;
  };

  return (
    <div className="w-full h-screen bg-linear-to-br from-gray-900 via-slate-900 to-gray-900 relative overflow-hidden">
      <div 
        className="absolute inset-0 opacity-10"
        style={{
          backgroundImage: `
            linear-gradient(rgba(139, 92, 246, 0.1) 1px, transparent 1px),
            linear-gradient(90deg, rgba(139, 92, 246, 0.1) 1px, transparent 1px)
          `,
          backgroundSize: '50px 50px'
        }}
      />

      <DraggableTerminal
        id="server-status"
        title="Server Status Monitor"
        icon={Terminal}
        initialPosition={{ x: 50, y: 50 }}
        initialSize={{ width: 700, height: 450 }}
        zIndex={getZIndex('server-status')}
        onFocus={() => bringToFront('server-status')}
      >
        <ServerStatusTerminal />
      </DraggableTerminal>

      <DraggableTerminal
        id="python-logs"
        title="Python Service Logs"
        icon={FileText}
        initialPosition={{ x: 400, y: 300 }}
        initialSize={{ width: 650, height: 400 }}
        zIndex={getZIndex('python-logs')}
        onFocus={() => bringToFront('python-logs')}
      >
        <PythonLogTerminal />
      </DraggableTerminal>

      <div className="absolute bottom-4 left-4 text-xs text-gray-500 space-y-1 pointer-events-none">
        <p>💡 <span className="text-cyan-400">Drag</span> terminals by header</p>
        <p>💡 <span className="text-purple-400">Resize</span> from any edge or corner</p>
        <p>💡 <span className="text-emerald-400">Reset</span> size with ↻ button</p>
      </div>

      <div className="absolute top-4 right-4 bg-black/80 p-4 rounded-lg text-xs text-gray-300 max-w-md border border-purple-500/30 font-mono">
        <h3 className="text-cyan-400 font-bold mb-2">📖 TypeScript Usage</h3>
        <pre className="text-[10px] overflow-x-auto">
{`// Define terminal in state
const [terminals, setTerminals] = 
  useState<Terminal[]>([
    { id: 'my-term', zIndex: 12 }
  ]);

// Use component
<DraggableTerminal
  id="my-term"
  title="My Terminal"
  icon={Terminal}
  initialPosition={{ x: 100, y: 100 }}
  initialSize={{ width: 600, height: 400 }}
  zIndex={getZIndex('my-term')}
  onFocus={() => bringToFront('my-term')}
>
  <YourComponent />
</DraggableTerminal>`}
        </pre>
      </div>
    </div>
  );
};

export default App;
