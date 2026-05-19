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
  eyebrow, title, description, aiVoiceName, maleVoices, femaleVoices,
  isLoading, errorMessage, previewingVoiceId, previewVisualizerBars,
  onVoiceChange, onPreviewVoice,
}: VoicePreferencesSectionProps) {
  const groups = [
    { id: "male", title: "Male", voices: maleVoices },
    { id: "female", title: "Female", voices: femaleVoices },
  ];

  return (
    <div>
      <SectionHeader eyebrow={eyebrow} title={title} description={description} />

      {isLoading ? (
        <p className="text-sm text-slate-400">Loading voices...</p>
      ) : errorMessage ? (
        <p className="text-sm text-red-400">{errorMessage}</p>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <div key={g.id}>
              <h3 className="text-xs text-slate-500 uppercase tracking-wider mb-3">{g.title} voices</h3>
              {g.voices.length === 0 ? (
                <p className="text-sm text-slate-500">None available</p>
              ) : (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {g.voices.map((voice) => (
                    <VoiceCard
                      key={voice.id}
                      voice={voice}
                      active={aiVoiceName === voice.id}
                      onSelect={() => onVoiceChange(voice)}
                      onPreview={() => onPreviewVoice(voice)}
                      isPreviewing={previewingVoiceId === voice.id}
                      visualizerBars={previewingVoiceId === voice.id ? previewVisualizerBars : []}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
