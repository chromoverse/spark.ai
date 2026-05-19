import { Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";

interface ChatMessage {
  id: string;
  role: "user" | "spark";
  text: string;
  timestamp: string;
}

export default function History() {
  const { on, off } = useSocket();
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    const onUserMsg = (data: any) => {
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: data.text || data.query || "", timestamp: new Date().toISOString() }]);
    };
    const onSparkMsg = (data: any) => {
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "spark", text: data.text || data.response || "", timestamp: new Date().toISOString() }]);
    };
    on("user-query", onUserMsg);
    on("spark-response", onSparkMsg);
    return () => { off("user-query", onUserMsg); off("spark-response", onSparkMsg); };
  }, [on, off]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <Clock size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Conversation History</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-3">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm">
            <Clock size={32} className="mb-2 opacity-40" />
            <p>No conversations yet</p>
            <p className="text-xs mt-1">Talk to Spark to see history here</p>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] px-3 py-2 rounded-lg text-sm ${
                  msg.role === "user"
                    ? "bg-blue-600/20 text-blue-100"
                    : "bg-slate-800 text-slate-200"
                }`}>
                  <p>{msg.text}</p>
                  <p className="text-[10px] text-slate-500 mt-1">{new Date(msg.timestamp).toLocaleTimeString()}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
