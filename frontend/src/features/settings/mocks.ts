import type { UserPreferences, TwoFactorState } from "./model";

export const mockPreferences: UserPreferences = {
  model: "qwen2.5-coder-32b",
  language: "en",
  rememberSearches: true,
  cacheEnabled: true,
  displayName: "OPERATOR",
};

export const mockTwoFactorState: TwoFactorState = {
  enabled: false,
  secret: "JBSWY3DPEHPK3PXP",
  backupCodes: [
    "8A3F-9C2E",
    "K7P2-M1X4",
    "R5N8-Q0W6",
    "T3H6-Y9B1",
    "V2D4-U7G5",
    "Z1E3-S8J0",
    "N9K5-L4F2",
    "W6C8-I3A7",
  ],
};

export const MODEL_OPTIONS = [
  { value: "qwen2.5-coder-32b", label: "qwen2.5-coder-32b" },
  { value: "llama3.3-70b", label: "llama3.3-70b" },
  { value: "mistral-nemo", label: "mistral-nemo" },
  { value: "gemma3-27b", label: "gemma3-27b" },
];

export const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "ja", label: "日本語" },
];
