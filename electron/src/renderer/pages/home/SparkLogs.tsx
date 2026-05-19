import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";

interface ToolLog {
  id: string;
  tool: string;
  status: "success" | "failed" | "running";
  timestamp: string;
  output?: string;
}

export default function SparkLogs() {
  const { on, off } = useSocket();
  const [logs, setLogs] = useState<ToolLog[]>([]);

  useEffect(() => {
    const handler = (data: any) => {
      setLogs((prev) => [
        { id: crypto.randomUUID(), tool: data.tool || "unknown", status: data.status || "success", timestamp: new Date().toISOString(), output: data.output },
        ...prev,
      ].slice(0, 100));
    };
    on("tool-execution-log", handler);
    return () => { off("tool-execution-log", handler); };
  }, [on, off]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <Activity size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Spark Logs</h2>
        <span className="text-xs text-slate-500 ml-auto">{logs.length} entries</span>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-3">
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Activity size={32} className="mb-2 opacity-40" />
            <p>No tool executions yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {logs.map((log) => (
              <div key={log.id} className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-white">{log.tool}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    log.status === "success" ? "bg-green-500/15 text-green-400" :
                    log.status === "failed" ? "bg-red-500/15 text-red-400" :
                    "bg-yellow-500/15 text-yellow-400"
                  }`}>{log.status}</span>
                </div>
                <p className="text-xs text-slate-500 mt-1">{new Date(log.timestamp).toLocaleTimeString()}</p>
                {log.output && <p className="text-xs text-slate-400 mt-1 truncate">{log.output}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
