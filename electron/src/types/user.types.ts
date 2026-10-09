export interface IUser {
  _id: string;

  username?: string;
  fullName?: string;
  email?: string;
  gender?: string;

  createdAt: string;
  lastLogin?: string;
  lastActiveAt?: string;

  isUserVerified: boolean;

  // --- Quota Flags ---
  isGeminiApiQuotaReached: boolean;
  isOpenrouterApiQuotaReached: boolean;

  // --- Preferences ---
  acceptsPromotionalEmails: boolean;
  language: string;
  aiGender: string;
  aiVoiceName?: string;
  theme: Partial<ThemePreferences>;
  notificationsEnabled: boolean;

  // API keys (unified dict)
  apiKeys: Record<string, string[]>;

  categoriesOfInterest: string[];
  favoriteBrands: string[];

  // --- Likes / Habits ---
  likedItems: string[];
  dislikedItems: string[];
  activityHabits: Record<string, unknown>;
  behavioralTags: string[];

  // --- Memories ---
  personalMemories: Record<string, unknown>[];
  reminders: Record<string, unknown>[];

  // --- Metrics ---
  preferencesHistory: Record<string, unknown>[];

  // --- Misc ---
  customAttributes: Record<string, unknown>;
}

export interface ThemePreferences {
  // Main background gradients/colors
  backgroundColor: string;
  borderColor: string;

  // Interactive element colors (hover, active)
  accentColor: string;
  accentColorHover: string;

  // Text colors
  textColorPrimary: string;
  textColorSecondary: string;

  // Specific component overrides if needed
  panelBackgroundCollapsed: string;
  panelBackgroundExpanded: string;
}
