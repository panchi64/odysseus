/** Settings feature data contracts. */

export interface UserPreferences {
  model: string;
  language: string;
  rememberSearches: boolean;
  cacheEnabled: boolean;
  displayName: string;
}

export interface TwoFactorState {
  enabled: boolean;
  secret: string;
  backupCodes: string[];
}

export type SettingsTab = "preferences" | "security" | "account";
