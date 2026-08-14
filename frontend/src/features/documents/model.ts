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

/* ── AI suggestions (DOC-3) ───────────────────────────────────────────────── */

export type SuggestionStatus = "pending" | "accepted" | "rejected";

/** One proposed change: replace `oldText` with `newText`. Nothing about it has been
 *  applied to the document — the backend applies it only when the operator accepts. */
export interface SuggestionChange {
  id: string;
  setId: string;
  /** Position within the set, in the order the AI produced them. */
  ordinal: number;
  oldText: string;
  newText: string;
  explanation: string;
  status: SuggestionStatus;
  /** The version accepting it minted; null while pending and forever if rejected. */
  version: number | null;
  createdAt: string;
  decidedAt: string | null;
}

/** One AI pass over a document — a group of independently reviewable changes. */
export interface SuggestionSet {
  id: string;
  documentId: string;
  conversationId: string | null;
  summary: string;
  createdAt: string;
  changes: SuggestionChange[];
  /** How many changes still await a decision — the backend's count, not a re-derivation. */
  pending: number;
}

/** What accepting returned: the document as it now stands, the single version the
 *  accepted changes minted (null when nothing applied), and the changes left pending
 *  because the document had moved underneath them. */
export interface SuggestionOutcome {
  body: string;
  version: number | null;
  accepted: string[];
  skipped: string[];
}
