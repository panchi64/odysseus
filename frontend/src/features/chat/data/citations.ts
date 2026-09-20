/**
 * The sources a completed tool call surfaced, read back off its persisted result.
 *
 * This is the **cold-reload counterpart** to the live `citation.added` fold: the stream
 * is handed citations the backend already derived, and a reloaded transcript has to
 * rebuild the same Sources row from the stored result instead.
 *
 * The two paths are not yet equal, and the gap is deliberate rather than forgotten —
 * `Citation.key`, `kind`, `engagement` and `snippet` are optional on the seam type
 * precisely because this path does not supply them. What it reconstructs is the address
 * and the title; the ladder and the fold key arrive only on the live stream.
 */

import type { Citation } from "../model";

/** Derive the citations a completed `web_search`/`web_fetch` tool call surfaced, in
 *  result order — the cold-reload counterpart to the live `citation.added` fold, so a
 *  reloaded transcript shows the same Sources row that streamed in. Cross-call dedup and
 *  the row numbering are the caller's concern (`toMessage` dedups by URL; the row numbers
 *  by position), so this neither dedups nor indexes. Anything else (a degraded-capability
 *  string, a still-running call, an unrecognized shape) yields none.
 *
 *  `web_search` now persists as a `SearchResults` object (`{ instruction, results }`), not
 *  a bare array — read `.results`. `web_fetch` persists as a single page object. */
export function citationsFromToolResult(
  name: string,
  result: unknown,
): Citation[] {
  if (name === "web_search") {
    const items = (result as { results?: unknown })?.results;
    if (!Array.isArray(items)) return [];
    const citations: Citation[] = [];
    for (const item of items) {
      if (
        !item ||
        typeof item !== "object" ||
        typeof (item as { url?: unknown }).url !== "string"
      )
        continue;
      const { url, title } = item as { url: string; title?: string };
      citations.push({ url, title });
    }
    return citations;
  }
  if (
    name === "web_fetch" &&
    result &&
    typeof result === "object" &&
    typeof (result as { url?: unknown }).url === "string"
  ) {
    const { url, title } = result as { url: string; title?: string };
    return [{ url, title }];
  }
  return [];
}
