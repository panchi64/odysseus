/** Documents feature data contracts. */

export type DocStatus = "active" | "archived";

export interface DocVersion {
  id: string;
  label: string;
  author: string;
  createdAt: string;
  /** Snapshot body text for restore/preview (Phase 1: mock content). */
  body: string;
}

export interface DocumentSummary {
  id: string;
  title: string;
  snippet: string;
  updatedAt: string;
  words: number;
  status: DocStatus;
}

export interface DocumentDetail extends DocumentSummary {
  body: string;
  versions: DocVersion[];
}
