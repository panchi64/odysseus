/** Gallery feature data contracts. */

/** v1 is images-only; the union exists so the seam can widen without a rename. */
export type MediaType = "image";

export interface MediaItem {
  id: string;
  title: string;
  type: MediaType;
  /** Always empty in v1 — kept so the seam can carry tags later. */
  tags: string[];
  favorite: boolean;
  /** Excluded from the knowledge-base / retrieval corpus when true. */
  kbExcluded: boolean;
  /** Album buckets this image belongs to: one provenance bucket
   *  (`sys-chat` | `sys-imported`) plus any custom album ids. */
  albumIds: string[];
  sizeBytes: number;
  createdAt: string;
}

export interface Album {
  id: string;
  name: string;
  count: number;
  /** Built-in bucket (`all` / `sys-chat` / `sys-imported`) — not editable. */
  system?: boolean;
}
