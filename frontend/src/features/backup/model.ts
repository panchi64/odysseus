/** Backup / restore feature data contracts. */

export interface BackupManifestItem {
  name: string;
  count: number;
}

export interface BackupManifest {
  createdAt: string;
  items: BackupManifestItem[];
}

export type BackupInclude =
  | "memories"
  | "skills"
  | "presets"
  | "settings"
  | "preferences";
