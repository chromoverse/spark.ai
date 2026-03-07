import SummaryCard from "../components/SummaryCard";
import SectionHeader from "../components/SectionHeader";
import {
  maskToken,
  prettifyValue,
  resolveHeardAboutSparkValue,
} from "../utils";

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

function TokenSummary({
  label,
  values,
}: {
  label: string;
  values: string[];
}) {
  const activeTokens = values.map((value) => value.trim()).filter(Boolean);

  return (
    <div className="rounded-[24px] border border-white/10 bg-black/15 px-5 py-4">
      <p className="text-[11px] uppercase tracking-[0.24em] text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-sm font-medium text-white">
        {activeTokens.length > 0
          ? `${activeTokens.length} token${activeTokens.length > 1 ? "s" : ""}`
          : "No keys added"}
      </p>
      {activeTokens.length > 0 ? (
        <div className="mt-3 space-y-2">
          {activeTokens.slice(0, 3).map((token, index) => (
            <p key={`${label}-${index}`} className="text-xs text-slate-400">
              {maskToken(token)}
            </p>
          ))}
          {activeTokens.length > 3 ? (
            <p className="text-xs text-slate-500">
              +{activeTokens.length - 3} more hidden entries
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function SummarySection({
  eyebrow,
  title,
  description,
  voiceDisplayName,
  draft,
}: SummarySectionProps) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col space-y-8">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SummaryCard label="Name" value={draft.preferredName || "Not set"} />
        <SummaryCard label="Profile gender" value={prettifyValue(draft.gender)} />
        <SummaryCard
          label="Heard about Spark"
          value={resolveHeardAboutSparkValue(
            draft.heardAboutSpark,
            draft.heardAboutSparkCustom,
          )}
        />
        <SummaryCard
          label="Spark tone"
          value={prettifyValue(draft.interactionStyle)}
        />
        <SummaryCard label="Language" value={prettifyValue(draft.language)} />
        <SummaryCard label="AI voice gender" value={prettifyValue(draft.aiGender)} />
        <SummaryCard
          label="AI voice name"
          value={voiceDisplayName || draft.aiVoiceName || "Not set"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <TokenSummary label="Gemini" values={draft.geminiApiKeys} />
        <TokenSummary label="Groq" values={draft.groqApiKeys} />
        <TokenSummary label="OpenRouter (optional)" values={draft.openrouterApiKeys} />
      </div>

      <div className="rounded-[26px] border border-white/10 bg-white/6 p-5 text-sm leading-7 text-slate-300">
        Spark will write these values to your profile only when you confirm on
        this screen. Blank token rows are ignored automatically.
      </div>
    </div>
  );
}
