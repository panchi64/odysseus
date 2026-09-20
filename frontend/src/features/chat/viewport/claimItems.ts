/**
 * The second reader's findings, folded into what the panel shows.
 *
 * The backend returns one row per claim→source pairing, so a claim two sources support
 * arrives twice. Folding them by the claim's own text is what turns that into the figure
 * the requirement actually asks for — **how many independent sources stand behind this
 * one assertion** — which the message-level inventory can only answer for the thread as
 * a whole.
 *
 * Presentation-only, like `sourceItems.ts` and `commandItems.ts` beside it. Nothing here
 * decides whether a claim is grounded, how confident the reading was, or which source it
 * rests on; all three arrive settled and are folded, never re-judged.
 *
 * **Ungrounded leads.** A claim whose own cited source does not appear to support it is
 * the single most valuable row on this surface — it is the defect the whole feature was
 * built to find — so it is not filed after the ones that worked out.
 */

import { hostLabel } from "~/lib/format";
import type {
  Claim,
  ClaimConfidence,
  MessageAttribution,
} from "../data/attributions";

/** One source standing behind a claim. */
export interface ClaimSource {
  /** The backend's own citation key, so a row ties to the inventory without matching
   *  on a title. Null when the reader could not name a source at all. */
  key: string | null;
  title: string | null;
  url: string | null;
  kind: string | null;
  /** The sentence the reader found. Null when it grounded nothing — which is the row
   *  worth reading, not a gap to hide. */
  passage: string | null;
}

/** One assertion the answer made, with everything found to stand behind it. */
export interface ClaimRow {
  claim: string;
  /** True when **any** sighting grounded it. A claim supported by one source and
   *  unsupported by another is a grounded claim with a weak source, not an ungrounded
   *  one — and both sources are listed so the operator can see that for themselves. */
  grounded: boolean;
  /** The strongest confidence across the sightings, on the same principle. */
  confidence: ClaimConfidence;
  sources: ClaimSource[];
  /** Distinct publishers behind those sources — the per-claim independent-source count.
   *  Counted over origins rather than sources for the reason the inventory's own figure
   *  is: four pages off one site are four sources and one origin. */
  origins: number;
  /** The turn that made it. The first, when a thread repeated itself. */
  messageId: string;
}

export interface ClaimInventory {
  /** Ungrounded first, then the rest — in first-sighting order within each. */
  items: ClaimRow[];
  ungroundedCount: number;
  /** How many assistant turns have a reading at all. */
  turns: number;
  /** The most recent extraction stamp, or null when nothing is stored. */
  newestExtraction: string | null;
}

const CONFIDENCE_ORDER: Record<ClaimConfidence, number> = {
  low: 0,
  medium: 1,
  high: 2,
};

/** The empty reading — what every non-research thread has, and every research answer
 *  that cited nothing. Absent is ordinary here and must render as nothing rather than as
 *  a heading over an empty list. */
export const NO_CLAIMS: ClaimInventory = {
  items: [],
  ungroundedCount: 0,
  turns: 0,
  newestExtraction: null,
};

/** What a claim's sources are counted as coming *from*. A page is its host; a corpus
 *  passage is the source it was indexed under, which is the nearest thing it has to a
 *  publisher. Falls back to the source's own key so an unnameable origin still counts as
 *  one rather than silently merging with every other unnameable one. */
function originOf(source: ClaimSource): string {
  if (source.url) return hostLabel(source.url);
  return source.title || source.key || "";
}

/** Identity for folding repeat sightings of one source under one claim. */
function sourceKeyOf(claim: Claim): string {
  return claim.sourceKey || claim.sourceUrl || claim.sourceTitle || "";
}

/**
 * Fold every stored reading in a thread into one list of claims.
 *
 * Claims fold by their **exact text**, which is deliberately strict: two near-identical
 * sentences are two claims here, and merging them would mean this layer deciding that
 * the model said the same thing twice. Overcounting claims is a readable mistake;
 * silently merging two assertions is not.
 */
export function collectClaims(
  attributions: MessageAttribution[],
): ClaimInventory {
  const byClaim = new Map<string, ClaimRow>();
  const seenSources = new Map<string, Set<string>>();
  let newest: string | null = null;

  for (const turn of attributions) {
    if (!newest || turn.extractedAt > newest) newest = turn.extractedAt;
    for (const claim of turn.claims) {
      const text = claim.claim.trim();
      if (!text) continue;
      let row = byClaim.get(text);
      if (!row) {
        row = {
          claim: text,
          grounded: false,
          confidence: "low",
          sources: [],
          origins: 0,
          messageId: turn.messageId,
        };
        byClaim.set(text, row);
        seenSources.set(text, new Set());
      }
      row.grounded = row.grounded || claim.grounded;
      if (CONFIDENCE_ORDER[claim.confidence] > CONFIDENCE_ORDER[row.confidence])
        row.confidence = claim.confidence;
      const key = sourceKeyOf(claim);
      const seen = seenSources.get(text)!;
      // A claim with no nameable source still deserves its row; it just contributes no
      // source to count. Keyed on the empty string, so several of them fold to one.
      if (key && !seen.has(key)) {
        seen.add(key);
        row.sources.push({
          key: claim.sourceKey,
          title: claim.sourceTitle,
          url: claim.sourceUrl,
          kind: claim.sourceKind,
          passage: claim.passage,
        });
      }
    }
  }

  const rows = [...byClaim.values()];
  for (const row of rows)
    row.origins = new Set(
      row.sources.map(originOf).filter((o) => o !== ""),
    ).size;

  // Stable within each half: `Map` preserves insertion order, which is first sighting.
  const ungrounded = rows.filter((r) => !r.grounded);
  return {
    items: [...ungrounded, ...rows.filter((r) => r.grounded)],
    ungroundedCount: ungrounded.length,
    turns: attributions.filter((t) => t.claims.length > 0).length,
    newestExtraction: newest,
  };
}
