/** Documents feature data contracts. */

export type DocStatus = "active" | "archived";

export interface DocVersion {
  id: string;
  /** Monotonic version number the backend restores by. */
  version: number;
  label: string;
  author: string;
  createdAt: string;
  /** Snapshot body text for restore/preview. */
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
