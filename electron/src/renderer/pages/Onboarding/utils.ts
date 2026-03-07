import type { OnboardingDraft } from "./types";

export const DEFAULT_TOKEN_ROWS = 3;
export const ACTIVE_ONBOARDING_LANGUAGE = "en";

export function ensureMinimumTokenRows(
  values: string[] | undefined,
  minimum: number = DEFAULT_TOKEN_ROWS,
) {
  const normalized = (values ?? []).map((value) => value ?? "");
  if (normalized.length >= minimum) {
    return normalized;
  }

  return [
    ...normalized,
    ...Array.from({ length: minimum - normalized.length }, () => ""),
  ];
}

export function trimTokens(values: string[]) {
  return values.map((value) => value.trim()).filter(Boolean);
}

export function countFilledTokens(values: string[]) {
  return trimTokens(values).length;
}

export function normalizeOnboardingLanguage(value?: string) {
  return value === ACTIVE_ONBOARDING_LANGUAGE ? value : ACTIVE_ONBOARDING_LANGUAGE;
}

export function normalizeOnboardingDraft(
  draft?: Partial<OnboardingDraft> | null,
): OnboardingDraft {
  return {
    preferredName: draft?.preferredName || "",
    fullName: draft?.fullName || "",
    gender: draft?.gender || "",
    heardAboutSpark: draft?.heardAboutSpark || "",
    heardAboutSparkCustom: draft?.heardAboutSparkCustom || "",
    interactionStyle: draft?.interactionStyle || "",
    language: normalizeOnboardingLanguage(draft?.language),
    aiGender: draft?.aiGender || "",
    aiVoiceName: draft?.aiVoiceName || "",
    geminiApiKeys: ensureMinimumTokenRows(draft?.geminiApiKeys),
    groqApiKeys: ensureMinimumTokenRows(draft?.groqApiKeys),
    openrouterApiKeys: ensureMinimumTokenRows(draft?.openrouterApiKeys),
  };
}

export function maskToken(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "Not added";
  }

  if (trimmed.length <= 8) {
    return "••••";
  }

  return `${trimmed.slice(0, 4)}...${trimmed.slice(-4)}`;
}

export function prettifyValue(value: string) {
  if (!value) {
    return "Not set";
  }

  if (value === "prefer_not_to_say") {
    return "Prefer not to say";
  }

  return value
    .split(/[_-]/g)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function resolveHeardAboutSparkValue(
  heardAboutSpark: string,
  heardAboutSparkCustom: string,
) {
  if (!heardAboutSpark) {
    return "Not set";
  }

  if (heardAboutSpark === "other") {
    return heardAboutSparkCustom.trim() || "Other";
  }

  if (heardAboutSpark === "youtube") {
    return "YouTube";
  }

  if (heardAboutSpark === "instagram") {
    return "Instagram";
  }

  if (heardAboutSpark === "friend") {
    return "Friend or referral";
  }

  if (heardAboutSpark === "x-twitter") {
    return "X / Twitter";
  }

  if (heardAboutSpark === "linkedin") {
    return "LinkedIn";
  }

  if (heardAboutSpark === "reddit") {
    return "Reddit";
  }

  if (heardAboutSpark === "github") {
    return "GitHub";
  }

  if (heardAboutSpark === "discord") {
    return "Discord";
  }

  return prettifyValue(heardAboutSpark);
}
