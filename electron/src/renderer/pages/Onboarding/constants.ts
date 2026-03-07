import type {
  ApiProvider,
  ApiSectionConfig,
  ChoiceOption,
  SectionMeta,
} from "./types";

export const sectionVariants = {
  enter: (direction: number) => ({
    opacity: 0,
    x: direction > 0 ? 96 : -96,
    filter: "blur(12px)",
  }),
  center: {
    opacity: 1,
    x: 0,
    filter: "blur(0px)",
  },
  exit: (direction: number) => ({
    opacity: 0,
    x: direction > 0 ? -96 : 96,
    filter: "blur(12px)",
  }),
};

export const sections: SectionMeta[] = [
  {
    id: "preferredName",
    eyebrow: "01 / Identity",
    title: "Set your name and profile basics.",
    description:
      "Use one name for now. Spark stores it as your profile name and uses it when it speaks to you.",
  },
  {
    id: "voicePreferences",
    eyebrow: "02 / Voice",
    title: "Choose Spark's voice.",
    description: "Preview a voice and pick the one Spark should use.",
  },
  {
    id: "heardAboutSpark",
    eyebrow: "03 / Intent",
    title: "Where did you hear about Spark?",
    description: "Pick the platform that brought you here.",
  },
  {
    id: "interactionStyle",
    eyebrow: "04 / Tone",
    title: "How should Spark talk back to you?",
    description: "Choose the response style that feels natural when the agent nudges you.",
  },
  {
    id: "language",
    eyebrow: "05 / Language",
    title: "Which language should feel native?",
    description:
      "English is active right now. Hindi and Nepali are listed as upcoming language updates.",
  },
  {
    id: "geminiKeys",
    eyebrow: "06 / API Entry",
    title: "Add your Gemini API keys.",
    description:
      "Add at least one Gemini API key so Spark can use Gemini-backed features.",
  },
  {
    id: "groqKeys",
    eyebrow: "07 / API Entry",
    title: "Add your Groq API keys.",
    description:
      "Add at least one Groq API key so Spark can use Groq-backed speech and realtime features.",
  },
  {
    id: "openrouterKeys",
    eyebrow: "08 / API Entry",
    title: "Add your OpenRouter API keys.",
    description:
      "OpenRouter is optional and acts as a fallback for supported routed model calls.",
  },
  {
    id: "summary",
    eyebrow: "09 / Launch",
    title: "Review your setup before Spark goes live.",
    description: "Everything stays in memory until this step. The final action syncs the profile once.",
  },
];

export const heardAboutOptions: ChoiceOption[] = [
  {
    value: "youtube",
    label: "YouTube",
    description: "You found Spark through a video, channel, or demo on YouTube.",
    iconKey: "youtube",
  },
  {
    value: "instagram",
    label: "Instagram",
    description: "You came across Spark through Instagram posts, reels, or stories.",
    iconKey: "instagram",
  },
  {
    value: "friend",
    label: "Friend or referral",
    description: "Someone directly told you about Spark and sent you here.",
    iconKey: "users",
  },
  {
    value: "x-twitter",
    label: "X / Twitter",
    description: "You discovered Spark from a post, thread, or mention on X.",
    iconKey: "twitter",
  },
  {
    value: "linkedin",
    label: "LinkedIn",
    description: "You found Spark from a LinkedIn post, creator, or professional share.",
    iconKey: "linkedin",
  },
  {
    value: "reddit",
    label: "Reddit",
    description: "You came across Spark through a Reddit post, thread, or community.",
    iconKey: "reddit",
  },
  {
    value: "github",
    label: "GitHub",
    description: "You found Spark through a repo, project page, or developer mention on GitHub.",
    iconKey: "github",
  },
  {
    value: "discord",
    label: "Discord",
    description: "You discovered Spark through a Discord server, community, or shared link.",
    iconKey: "discord",
  },
  {
    value: "other",
    label: "Other source",
    description: "Pick this if the source was somewhere else and type the exact source.",
    iconKey: "globe",
  },
];

export const interactionOptions: ChoiceOption[] = [
  {
    value: "gen-z",
    label: "Gen Z",
    description: "More casual, internet-native wording with a lighter tone.",
  },
  {
    value: "minimal",
    label: "Minimal",
    description: "Short, stripped-down replies with minimal wording and friction.",
  },
  {
    value: "professional",
    label: "Professional",
    description: "Clear, polished, work-ready responses with a more formal tone.",
  },
];

export const languageOptions: ChoiceOption[] = [
  {
    value: "en",
    label: "English",
    description: "Full UI support and voice preview support are available right now.",
  },
  {
    value: "hi",
    label: "Hindi",
    description: "Upcoming in a future update. English stays active for now.",
    badge: "Upcoming",
    disabled: true,
  },
  {
    value: "ne",
    label: "Nepali",
    description: "Upcoming in a future update. English stays active for now.",
    badge: "Upcoming",
    disabled: true,
  },
];

export const genderOptions: ChoiceOption[] = [
  {
    value: "male",
    label: "Male",
    description: "Store profile gender as male.",
  },
  {
    value: "female",
    label: "Female",
    description: "Store profile gender as female.",
  },
  {
    value: "prefer_not_to_say",
    label: "Prefer not to say",
    description: "Keep profile gender unset for personalization.",
  },
];

export const aiVoiceGenderOptions: ChoiceOption[] = [
  {
    value: "male",
    label: "Male voice",
    description: "Choose from the currently available male voice set.",
  },
  {
    value: "female",
    label: "Female voice",
    description: "Choose from the currently available female voice set.",
  },
];

const GEMINI_HELP_URL = "https://aistudio.google.com/app/apikey";
const GROQ_HELP_URL = "https://console.groq.com/keys";
const GROQ_ENABLE_URL =
  "https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english";
const OPENROUTER_HELP_URL = "https://openrouter.ai/settings/keys";
export const MIN_GEMINI_API_KEYS = 1;
export const MIN_GROQ_API_KEYS = 1;

export const apiSectionConfigs: Record<ApiProvider, ApiSectionConfig> = {
  gemini: {
    provider: "gemini",
    title: "Gemini API keys",
    description:
      "Gemini is required. Add at least one working key to continue onboarding.",
    minimumRequired: MIN_GEMINI_API_KEYS,
    helpTitle: "See how to get API key",
    helpDescription:
      "Open the Gemini key page, create your keys, and paste them back into the fields on the left.",
    links: [
      {
        label: "Open Gemini key page",
        url: GEMINI_HELP_URL,
        description: "Generate Gemini API keys in Google AI Studio.",
      },
    ],
  },
  groq: {
    provider: "groq",
    title: "Groq API keys",
    description:
      "Groq is required. Add at least one key, then enable the speech playground required for TTS and STT.",
    minimumRequired: MIN_GROQ_API_KEYS,
    helpTitle: "See how to get API key",
    helpDescription:
      "Create Groq keys, paste them here, and open the Groq playground to enable the speech model.",
    links: [
      {
        label: "Open Groq key page",
        url: GROQ_HELP_URL,
        description: "Create the Groq API keys you want Spark to use.",
      },
      {
        label: "Enable Groq speech playground",
        url: GROQ_ENABLE_URL,
        description: "Visit this page so Groq TTS and STT can be enabled.",
      },
    ],
  },
  openrouter: {
    provider: "openrouter",
    title: "OpenRouter API keys",
    description:
      "Optional fallback. Add OpenRouter keys only if you want Spark to route supported calls through OpenRouter.",
    minimumRequired: 0,
    optional: true,
    helpTitle: "See how to get API key",
    helpDescription:
      "Open OpenRouter settings, create keys, and paste them back into the token list.",
    links: [
      {
        label: "Open OpenRouter key page",
        url: OPENROUTER_HELP_URL,
        description: "Generate OpenRouter API keys in account settings.",
      },
    ],
  },
};
