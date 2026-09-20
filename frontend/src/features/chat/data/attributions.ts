/**
 * What a second reader found when it read the answer against the sources it cited.
 *
 * A research answer cites at the *message* level, so the operator can see that a page was
 * read and never which sentence carried the claim. The backend closes that with a pass
 * after the answer, over the answer: the finished prose and the sources the turn retained
 * go to a background model, which returns claim → source → passage triples.
 *
 * **The ungrounded row is the point, not the failure case.** A claim that names a source
 * and carries no passage from it means the answer pointed at a page and a second reader
 * could not find the assertion in it. Nothing here treats that as missing data.
 *
 * **Absent is ordinary.** Every non-research thread has none of this, and so does every
 * research answer that cited nothing. An empty read is not an error and must never blank
 * the message-level sources the panel already shows.
 *
 * Fetched rather than derived — unlike the source inventory and the command log, which
 * come off the transcript. This is not in the transcript: it is a separate reading the
 * backend stores sealed, and it is served on its own route so a thread that never shows
 * the panel does not pay to unseal it on every open.
 */

import { api } from "~/lib/api";

/** How sure the reader was that this passage supports this claim. */
export type ClaimConfidence = "high" | "medium" | "low";

/** One claim an answer made, and the source it does — or does not — rest on. */
export interface Claim {
  claim: string;
  /** **Not the same question as "is `passage` null".** A claim can name a source and
   *  still carry no passage from it; that row arrives fully populated and says so. */
  grounded: boolean;
  /** The same key `citation.added` carries, so a claim joins to its inventory row
   *  without matching on a title or a URL. Null when no source could be named at all. */
  sourceKey: string | null;
  sourceTitle: string | null;
  /** Null for a corpus passage, which has a locator rather than an address — the same
   *  rule `Citation.url` follows. */
  sourceUrl: string | null;
  sourceKind: "web" | "corpus" | null;
  /** The supporting words from the source; null when nothing grounded the claim. */
  passage: string | null;
  confidence: ClaimConfidence;
  /** A character position into the turn's own text where `claim` begins, already
   *  verified server-side. Null means no trustworthy position was reported — an ordinary
   *  outcome, and never a reason to drop the claim. */
  offset: number | null;
}

/** One assistant turn's reading, keyed by the same id the message carries. */
export interface MessageAttribution {
  messageId: string;
  extractedAt: string;
  claims: Claim[];
}

interface ClaimDTO {
  claim: string;
  grounded: boolean;
  source_key: string | null;
  source_title: string | null;
  source_url: string | null;
  source_kind: "web" | "corpus" | null;
  passage: string | null;
  confidence: ClaimConfidence;
  offset: number | null;
}

interface AttributionDTO {
  conversation_id: string;
  messages: {
    message_id: string;
    extracted_at: string;
    claims: ClaimDTO[];
  }[];
}

function toClaim(dto: ClaimDTO): Claim {
  return {
    claim: dto.claim,
    grounded: dto.grounded,
    sourceKey: dto.source_key,
    sourceTitle: dto.source_title,
    sourceUrl: dto.source_url,
    sourceKind: dto.source_kind,
    passage: dto.passage,
    confidence: dto.confidence,
    offset: dto.offset,
  };
}

function toAttributions(dto: AttributionDTO): MessageAttribution[] {
  return dto.messages.map((m) => ({
    messageId: m.message_id,
    extractedAt: m.extracted_at,
    claims: m.claims.map(toClaim),
  }));
}

/** Everything stored for a thread, oldest turn first. An empty list is the ordinary
 *  answer and is not an error. */
export async function fetchAttributions(
  conversationId: string,
): Promise<MessageAttribution[]> {
  return toAttributions(
    await api.get<AttributionDTO>(
      `/conversations/${conversationId}/attributions`,
    ),
  );
}

/** Run the extraction over a turn that has none — the retroactive path, for threads that
 *  finished before the pass existed and for a turn whose live pass degraded.
 *
 *  The backend runs its own trigger, so this is safe to offer on any thread: one that
 *  does not want a reading spends no model call and answers with whatever was stored. */
export async function extractAttributions(
  conversationId: string,
  messageId?: string,
): Promise<MessageAttribution[]> {
  return toAttributions(
    await api.post<AttributionDTO>(
      `/conversations/${conversationId}/attributions`,
      { message_id: messageId ?? null },
    ),
  );
}
