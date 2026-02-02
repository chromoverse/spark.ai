import React, { useState, } from 'react';
import { Info, Maximize2, Minimize2, RotateCcw, Terminal, FileText } from 'lucide-react';
import { DraggableTerminal } from './DraggableTerminal';
import ServerStatusShower from './ServerStatusTerminal';
import { PythonLogTerminal } from './PythonLogTerminal';


interface Terminal {
    id: string;
    zIndex: number;
  }
  

function TerminalShower() {
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
        <div className="w-full h-full bg-linear-to-br from-gray-950 via-slate-900 to-gray-950 relative overflow-hidden">
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
            <ServerStatusShower />
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
    
          <div className="absolute top-4 right-4 text-xs text-gray-500 space-y-1 pointer-events-none">
            <p>💡 <span className="text-cyan-400">Drag</span> terminals by header</p>
            <p>💡 <span className="text-purple-400">Resize</span> from any edge or corner</p>
            <p>💡 <span className="text-emerald-400">Reset</span> size with ↻ button</p>
          </div>
    
        </div>
      );
}

export default TerminalShower

// <div className="absolute top-4 right-4 bg-black/80 p-4 rounded-lg text-xs text-gray-300 max-w-md border border-purple-500/30 font-mono">
// <h3 className="text-cyan-400 font-bold mb-2">📖 TypeScript Usage</h3>
// <pre className="text-[10px] overflow-x-auto">
// {`// Define terminal in state
// const [terminals, setTerminals] = 
// useState<Terminal[]>([
// { id: 'my-term', zIndex: 12 }
// ]);

// // Use component
// <DraggableTerminal
// id="my-term"
// title="My Terminal"
// icon={Terminal}
// initialPosition={{ x: 100, y: 100 }}
// initialSize={{ width: 600, height: 400 }}
// zIndex={getZIndex('my-term')}
// onFocus={() => bringToFront('my-term')}
// >
// <YourComponent />
// </DraggableTerminal>`}
// </pre>
// </div>
