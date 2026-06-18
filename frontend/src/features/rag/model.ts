/** RAG / Knowledge Base feature data contracts. */

import type { IconName } from "~/ui";

export type RagIndexStatus = "indexed" | "indexing" | "stale" | "error";

/** Where a source's content originates.
 *  - `surface`: an in-app corpus surface (Documents, Uploads, Gallery, Memory,
 *    Research) that is auto-indexed and managed on its own page. Not removable
 *    here — it's part of the system.
 *  - `folder`: an operator-added host path the server crawls and indexes.
 *    Removable. */
export type RagSourceKind = "surface" | "folder";

export interface RagSource {
  id: string;
  kind: RagSourceKind;
  /** Display name. For a `surface` it's the surface name ("Documents"); for a
   *  `folder` it's the host path. */
  label: string;
  /** Row icon — surfaces echo their nav icon; folders fall back to a path glyph. */
  icon: IconName;
  /** Surfaces link to the page that manages them (e.g. "/documents"). */
  href?: string;
  docCount: number;
  status: RagIndexStatus;
  lastIndexedAt: string;
  /** Short reason code for the last error, e.g. "PATH NOT FOUND". Phase 2 populated by backend. */
  errorHint?: string;
}

export interface RagIndexStats {
  embeddingModel: string;
  dims: number;
  totalDocs: number;
  totalCollections: number;
  storeSize: string;
}
