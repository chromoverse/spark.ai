/**
 * Notice banner shown during onboarding to inform users about expanded LLM provider support.
 * Displayed as a fixed top banner on API key sections.
 */
export default function ExpandedProvidersNotice() {
  return (
    <div className="mb-4 rounded-lg border border-[#d97757]/20 bg-[#d97757]/5 px-4 py-3">
      <p className="text-xs font-medium text-[#d97757]">
        Expanded LLM Support
      </p>
      <p className="mt-1 text-[11px] text-white/40 leading-relaxed">
        Spark now routes across <span className="text-white font-medium">6 providers</span> — Groq, Gemini, Cerebras, SambaNova, Mistral, and OpenRouter.
        More keys = more free quota = longer uninterrupted sessions.
        Only Gemini and Groq are required. The rest are optional but recommended.
      </p>
    </div>
  );
}
