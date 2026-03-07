import SectionHeader from "../components/SectionHeader";
import VoiceCard from "../components/VoiceCard";
import type { VoiceCatalogEntry } from "../types";

interface VoicePreferencesSectionProps {
  eyebrow: string;
  title: string;
  description: string;
  aiVoiceName: string;
  maleVoices: VoiceCatalogEntry[];
  femaleVoices: VoiceCatalogEntry[];
  isLoading: boolean;
  errorMessage: string | null;
  previewingVoiceId: string | null;
  previewVisualizerBars: number[];
  onVoiceChange: (voice: VoiceCatalogEntry) => void;
  onPreviewVoice: (voice: VoiceCatalogEntry) => void;
}

export default function VoicePreferencesSection({
  eyebrow,
  title,
  description,
  aiVoiceName,
  maleVoices,
  femaleVoices,
  isLoading,
  errorMessage,
  previewingVoiceId,
  previewVisualizerBars,
  onVoiceChange,
  onPreviewVoice,
}: VoicePreferencesSectionProps) {
  const sections = [
    {
      id: "male",
      title: "Male voices",
      voices: maleVoices,
    },
    {
      id: "female",
      title: "Female voices",
      voices: femaleVoices,
    },
  ];

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className="rounded-[28px] border border-white/12 bg-[rgba(10,15,28,0.58)] p-5 backdrop-blur-xl">
        {isLoading ? (
          <p className="text-sm text-slate-300">Loading voice catalog...</p>
        ) : errorMessage ? (
          <p className="text-sm text-red-300">{errorMessage}</p>
        ) : sections.every((group) => group.voices.length === 0) ? (
          <p className="text-sm text-slate-300">
            No voices are available right now.
          </p>
        ) : (
          <div className="space-y-6">
            {sections.map((group) => (
              <div key={group.id} className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-semibold text-white">{group.title}</h3>
                  <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    {group.voices.length} options
                  </span>
                </div>

                {group.voices.length === 0 ? (
                  <div className="rounded-[22px] border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-400">
                    No {group.title.toLowerCase()} are available right now.
                  </div>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-2">
                    {group.voices.map((voice) => (
                      <VoiceCard
                        key={voice.id}
                        voice={voice}
                        active={aiVoiceName === voice.id}
                        onSelect={() => onVoiceChange(voice)}
                        onPreview={() => onPreviewVoice(voice)}
                        isPreviewing={previewingVoiceId === voice.id}
                        visualizerBars={
                          previewingVoiceId === voice.id ? previewVisualizerBars : []
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
