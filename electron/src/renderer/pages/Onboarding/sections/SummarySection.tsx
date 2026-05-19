import SectionHeader from "../components/SectionHeader";
import { maskToken, prettifyValue, resolveHeardAboutSparkValue } from "../utils";

interface SummarySectionProps {
  eyebrow: string;
  title: string;
  description: string;
  voiceDisplayName?: string;
  draft: {
    preferredName: string;
    fullName: string;
    gender: string;
    heardAboutSpark: string;
    heardAboutSparkCustom: string;
    interactionStyle: string;
    language: string;
    aiGender: string;
    aiVoiceName: string;
    geminiApiKeys: string[];
    groqApiKeys: string[];
    openrouterApiKeys: string[];
  };
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-4 py-3 bg-slate-900 rounded-lg">
      <p className="text-[11px] text-slate-500 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-sm text-white">{value || "Not set"}</p>
    </div>
  );
}

function TokenSummary({ label, values }: { label: string; values: string[] }) {
  const active = values.filter((v) => v.trim());
  return (
    <div className="px-4 py-3 bg-slate-900 rounded-lg">
      <p className="text-[11px] text-slate-500 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-sm text-white">{active.length} key{active.length !== 1 ? "s" : ""}</p>
      {active.slice(0, 2).map((t, i) => (
        <p key={i} className="text-xs text-slate-500 mt-0.5">{maskToken(t)}</p>
      ))}
    </div>
  );
}

export default function SummarySection({ eyebrow, title, description, voiceDisplayName, draft }: SummarySectionProps) {
  return (
    <div>
      <SectionHeader eyebrow={eyebrow} title={title} description={description} />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Item label="Name" value={draft.preferredName} />
        <Item label="Gender" value={prettifyValue(draft.gender)} />
        <Item label="Heard about" value={resolveHeardAboutSparkValue(draft.heardAboutSpark, draft.heardAboutSparkCustom)} />
        <Item label="Tone" value={prettifyValue(draft.interactionStyle)} />
        <Item label="Language" value={prettifyValue(draft.language)} />
        <Item label="Voice" value={voiceDisplayName || draft.aiVoiceName || "Not set"} />
      </div>

      <div className="grid gap-3 md:grid-cols-3 mt-4">
        <TokenSummary label="Gemini" values={draft.geminiApiKeys} />
        <TokenSummary label="Groq" values={draft.groqApiKeys} />
        <TokenSummary label="OpenRouter" values={draft.openrouterApiKeys} />
      </div>
    </div>
  );
}
