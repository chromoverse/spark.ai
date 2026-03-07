export type OnboardingPhase = "intro" | "form";

export type VoiceGender = "male" | "female";

export type ApiProvider = "gemini" | "groq" | "openrouter";

export type SectionId =
  | "preferredName"
  | "voicePreferences"
  | "heardAboutSpark"
  | "interactionStyle"
  | "language"
  | "geminiKeys"
  | "groqKeys"
  | "openrouterKeys"
  | "summary";

export interface ChoiceOption {
  value: string;
  label: string;
  description: string;
  badge?: string;
  disabled?: boolean;
  iconKey?: string;
}

export interface SectionMeta {
  id: SectionId;
  eyebrow: string;
  title: string;
  description: string;
}

export interface VoiceCatalogEntry {
  id: string;
  name: string;
  gender: VoiceGender;
  languageCodes: string[];
  iconPath: string;
  audioPath: string;
  iconUrl?: string;
  audioUrl?: string;
}

export interface OnboardingDraft {
  preferredName: string;
  fullName: string;
  gender: string;
  heardAboutSpark: string;
  heardAboutSparkCustom: string;
  interactionStyle: string;
  language: string;
  aiGender: VoiceGender | "";
  aiVoiceName: string;
  geminiApiKeys: string[];
  groqApiKeys: string[];
  openrouterApiKeys: string[];
}

export interface OnboardingLocationState {
  onboardingDraft?: OnboardingDraft;
  skipIntro?: boolean;
  resumeAtReview?: boolean;
}

export interface HelpLink {
  label: string;
  url: string;
  description?: string;
}

export interface ApiSectionConfig {
  provider: ApiProvider;
  title: string;
  description: string;
  minimumRequired: number;
  optional?: boolean;
  helpTitle: string;
  helpDescription: string;
  links: HelpLink[];
}
