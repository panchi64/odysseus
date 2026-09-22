/** What triggered a fold, in the words the panel reports it with.
 *
 *  The sibling of `contextLabels.ts`, and for the same reason: the backend sends an enum
 *  because the wording of a readout is presentation, and two surfaces then need the same
 *  value to become the same words. The in-flight panel and the checkpoint it settles into
 *  are one fold seen at two moments; naming it "Request too large" in one and "overflow"
 *  in the other would leave the operator working out that they are the same event.
 *
 *  **Stated, not addressed.** These used to read as asides to the operator — "You asked",
 *  "you asked for it" — which was the right voice for the sentence they used to sit in and
 *  the wrong one now: the fold renders as a console readout in the machine register (§2),
 *  where a panel that turns round and speaks to the reader is the one line that breaks the
 *  register. A trigger is a fact about the run, so it is named like one.
 *
 *  Why the difference is worth carrying at all: a fold the operator asked for, one that
 *  fired at their own threshold, and one the provider forced by refusing an oversized
 *  request are three different things to have happened, and only the last means the turn
 *  nearly died.
 */

import type { CompactionReason } from "./model";

/** The trigger, named as the panel's own row value. */
const CAUSE: Record<CompactionReason, string> = {
  threshold: "threshold reached",
  overflow: "provider refused the request as too large",
  manual: "manual trigger",
};

/** Narrow a wire string to a reason this file can actually word, or `undefined`.
 *
 *  The cold read carries the reason as a plain string (it is read back off a stored
 *  message, so a checkpoint folded before the backend recorded one has none, and a
 *  future backend could name a trigger this build has never heard of). Both cases have
 *  the same right answer: fall back to the ordinary trigger rather than trusting the
 *  string through, which would print a raw enum id at the operator.
 *
 *  `Object.hasOwn`, not `in`: the value is a wire string, and `in` would accept
 *  `"toString"` and hand back a `CAUSE` lookup that is a function. */
export function asCompactionReason(
  value: string | null | undefined,
): CompactionReason | undefined {
  return value && Object.hasOwn(CAUSE, value)
    ? (value as CompactionReason)
    : undefined;
}

export function compactionReasonCause(reason: CompactionReason): string {
  return CAUSE[reason];
}
