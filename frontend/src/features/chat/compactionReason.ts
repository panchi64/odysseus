/** What triggered a fold, in the operator's words.
 *
 *  The sibling of `contextLabels.ts`, and for the same reason: the backend sends an
 *  enum because the wording of a readout is presentation, and two surfaces then need
 *  the same value to become the same words. The in-flight row on the rail and the
 *  divider it settles into are one fold seen at two moments; naming it "Request too
 *  large" in one and "overflow" in the other would leave the operator working out that
 *  they are the same event.
 *
 *  **Two forms, because the two surfaces have different room.** The divider states its
 *  reason as one segment of a centered single-line label already carrying a message
 *  count and a token delta, so it gets a noun phrase. The rail row is a full-width row
 *  the operator is looking at *while they wait*, so it gets the sentence — which is
 *  also where the difference matters most: a fold the operator asked for and a fold the
 *  provider forced are the same pause otherwise, and they are not the same thing to
 *  have happen to your turn. */

import type { CompactionReason } from "./model";

/** The divider's segment — short enough to sit beside two other facts. */
const SEGMENT: Record<CompactionReason, string> = {
  threshold: "Window filled",
  overflow: "Request too large",
  manual: "You asked",
};

/** The rail row's clause, completing "Compacting because …". */
const CAUSE: Record<CompactionReason, string> = {
  threshold: "the window reached your trigger point",
  overflow: "the model refused the request as too large",
  manual: "you asked for it",
};

export function compactionReasonSegment(reason: CompactionReason): string {
  return SEGMENT[reason];
}

export function compactionReasonCause(reason: CompactionReason): string {
  return CAUSE[reason];
}
