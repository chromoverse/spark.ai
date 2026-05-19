import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import MinimalHeader from "@/components/local/MinimalHeader";

export default function PrivacyPolicy() {
  const navigate = useNavigate();

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col select-none">
      <MinimalHeader />
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-2xl mx-auto">
          <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-sm text-slate-400 hover:text-white mb-6 transition-colors">
            <ArrowLeft size={14} /> Back
          </button>

          <h1 className="text-2xl font-semibold mb-6">Privacy Policy</h1>

          <div className="space-y-5 text-sm text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-white font-medium mb-2">Data Collection</h2>
              <p>Spark collects only the data necessary to provide a personalized AI assistant experience. This includes your email address, display name, voice preferences, and API keys you provide during onboarding.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">Local Processing</h2>
              <p>Spark is designed as a desktop-first application. Your conversations, tool executions, and personal data are processed locally on your machine. We do not store conversation history on external servers unless you explicitly enable cloud sync.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">API Keys</h2>
              <p>Your API keys (Gemini, Groq, OpenRouter) are stored securely using your system's native credential manager. They are never transmitted to our servers and are only used to make requests to the respective AI providers on your behalf.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">Third-Party Services</h2>
              <p>When you connect external services (Google, Spotify, etc.) via OAuth, Spark only requests the minimum permissions needed. You can revoke access at any time from the External Services settings.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">Voice Data</h2>
              <p>Voice input is processed locally using on-device speech recognition when available. Audio data is never stored permanently and is discarded after transcription.</p>
            </section>

            <section>
              <h2 className="text-white font-medium mb-2">Your Rights</h2>
              <p>You can delete your account and all associated data at any time. You have full control over what Spark remembers about you through the Memory & Context settings.</p>
            </section>

            <p className="text-slate-500 text-xs pt-4">Last updated: May 2026</p>
          </div>
        </div>
      </div>
    </div>
  );
}
