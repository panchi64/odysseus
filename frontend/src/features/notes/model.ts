/** Notes feature data contracts. */

export interface ChecklistItem {
  id: string;
  text: string;
  done: boolean;
}

export type NoteTone = "nominal" | "info" | "warn" | "alert" | "dim";

export interface Note {
  id: string;
  title: string;
  body: string;
  label?: string;
  tone?: NoteTone;
  pinned: boolean;
  dueAt?: string; // ISO datetime
  checklist?: ChecklistItem[];
  reminderAt?: string; // ISO datetime
  createdAt: string;
  updatedAt: string;
}
