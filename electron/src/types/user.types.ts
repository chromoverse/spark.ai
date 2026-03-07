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

  geminiApiKeys: string[];
  openrouterApiKeys: string[];
  groqApiKeys: string[];

  categoriesOfInterest: string[];
  favoriteBrands: string[];

  // --- Likes / Habits ---
  likedItems: string[];
  dislikedItems: string[];
  activityHabits: Record<string, any>;
  behavioralTags: string[];

  // --- Memories ---
  personalMemories: Record<string, any>[];
  reminders: Record<string, any>[];

  // --- Metrics ---
  preferencesHistory: Record<string, any>[];

  // --- Misc ---
  customAttributes: Record<string, any>;
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
