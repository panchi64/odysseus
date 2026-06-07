import type { BackupManifest } from "./model";

export const mockLastBackup: BackupManifest = {
  createdAt: "2026-06-05T03:00:00Z",
  items: [
    { name: "memories", count: 412 },
    { name: "skills", count: 8 },
    { name: "presets", count: 14 },
    { name: "settings", count: 1 },
    { name: "preferences", count: 1 },
  ],
};
