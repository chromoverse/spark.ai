import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import MinimalHeader from "@/components/local/MinimalHeader";
import SparkIcon from "../../assets/icon.png";

export default function About() {
  const navigate = useNavigate();

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col select-none">
      <MinimalHeader />
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-2xl mx-auto">
          <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-sm text-slate-400 hover:text-white mb-6 transition-colors">
            <ArrowLeft size={14} /> Back
          </button>

          {/* Project */}
          <div className="flex items-center gap-3 mb-6">
            <img src={SparkIcon} className="w-10" />
            <div>
              <h1 className="text-2xl font-semibold">Spark</h1>
              <p className="text-sm text-slate-400">v1.0.0 · by Chromoverse</p>
            </div>
          </div>

          <div className="space-y-5 text-sm text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-white font-medium mb-2">About Spark</h2>
              <p>Spark is a next-generation personal AI assistant built for the desktop. Unlike cloud-only assistants, Spark runs locally on your machine — giving you full control over your data, privacy, and workflow.</p>
              <p className="mt-2">It combines voice interaction, intelligent task execution, system automation, and multi-provider LLM support into a single seamless experience. From opening apps and managing files to sending messages and booking appointments — Spark handles it all through natural conversation.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">What Makes Spark Different</h2>
              <ul className="space-y-1.5 text-slate-400">
                <li>• Desktop-native with full system access</li>
                <li>• Privacy-first — your data stays on your machine</li>
                <li>• Multi-provider AI (Gemini, Groq, OpenRouter)</li>
                <li>• Real-time voice with wake-word detection</li>
                <li>• Extensible plugin and tool system</li>
                <li>• Smart memory and context awareness</li>
              </ul>
            </section>

            {/* Developer */}
            <section className="pt-4 border-t border-slate-800">
              <h2 className="text-white font-medium mb-2">The Developer</h2>
              <p>Spark is created and maintained by <span className="text-white font-medium">Siddhant</span> — a full-stack engineer, AI enthusiast, and the founder of Chromoverse.</p>
              <p className="mt-2">Siddhant is a self-taught developer who started coding at a young age and has since built expertise across the entire stack — from low-level system programming to modern AI/ML pipelines. He architects and builds every layer of Spark single-handedly: the Python backend, the Electron desktop client, the voice daemon, the LLM orchestration engine, the tool execution framework, and the real-time communication layer.</p>
              <p className="mt-2">His vision with Spark is to create an AI assistant that truly respects user privacy while being more capable than any cloud-only alternative. He believes the future of personal AI is local-first, and Spark is his proof of that conviction.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">Chromoverse</h2>
              <p>Chromoverse is the umbrella under which Spark and future AI-powered products are developed. The mission is simple: build intelligent software that empowers individuals — not corporations.</p>
            </section>

            <p className="text-slate-500 text-xs pt-4">Built with ❤️ in Nepal</p>
          </div>
        </div>
      </div>
    </div>
  );
}
