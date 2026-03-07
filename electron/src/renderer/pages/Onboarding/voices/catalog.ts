import type { VoiceCatalogEntry, VoiceGender } from "../types";

const voiceCatalogUrl = new URL("./catalog.json", import.meta.url);

export const onboardingIntroAudioUrl = new URL(
  "./assets/onboarding-intro.wav",
  import.meta.url,
).toString();

export async function loadVoiceCatalog(): Promise<VoiceCatalogEntry[]> {
  const response = await fetch(voiceCatalogUrl.toString());
  if (!response.ok) {
    throw new Error(`Failed to load voice catalog: ${response.status}`);
  }

  const rawCatalog = (await response.json()) as VoiceCatalogEntry[];

  return rawCatalog.map((entry) => ({
    ...entry,
    iconUrl: new URL(entry.iconPath, voiceCatalogUrl).toString(),
    audioUrl: new URL(entry.audioPath, voiceCatalogUrl).toString(),
  }));
}

export function getVoicesForLanguageAndGender(
  catalog: VoiceCatalogEntry[],
  language: string,
  gender: VoiceGender | "",
) {
  if (!gender) {
    return [];
  }

  const exactMatches = catalog.filter(
    (voice) =>
      voice.gender === gender && voice.languageCodes.includes(language || "en"),
  );

  if (exactMatches.length > 0) {
    return exactMatches;
  }

  return catalog.filter(
    (voice) => voice.gender === gender && voice.languageCodes.includes("en"),
  );
}
