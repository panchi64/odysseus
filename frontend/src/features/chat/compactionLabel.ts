/** The compaction divider's one-line label, derived rather than rendered.
 *
 *  Split out of `CompactionDivider.tsx` because it is the part with rules: which of the
 *  four facts a given fold actually has to report, and how each is worded. The component
 *  is then the rule of thumb this codebase keeps everywhere — a screen renders a
 *  derivation, it doesn't perform one — and this is testable without a DOM.
 */

import {
  asCompactionReason,
  compactionReasonSegment,
} from "./compactionReason";
import type { ChatMessage } from "./model";

/** A token count at the magnitude a reader actually compares — the divider's job is
 *  to show that the fold worked, not to audit it, and `62,431 → 4,102` buries that in
 *  digits. Under a thousand the exact number is already short enough to print. */
export function approxTokens(n: number): string {
  if (n >= 1_000_000) return `~${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `~${Math.round(n / 1_000)}k`;
  return `~${n}`;
}

/** The label's segments, in order, with every one this fold can't report left out.
 *
 *  Three guards and they are deliberately not the same shape. The counts are guarded on
 *  `> 0`, because the backend always sends them and 0 means "nothing to report" — a fold
 *  whose estimate rounds to nothing on both sides would otherwise print `~0 → ~0`, a
 *  number on screen that answers no question. The reason is guarded on **presence**,
 *  because it genuinely can be missing: it is stored on the checkpoint now, so a reload
 *  names the cause the operator watched arrive, but a thread folded before the backend
 *  recorded reasons has none. Hence a segment rather than a rewritten label — the
 *  sentence has to read correctly without it. */
export function compactionLabelParts(message: ChatMessage): string[] {
  const parts = ["Context compacted"];
  const reason = asCompactionReason(message.compactionReason);
  if (reason) parts.push(compactionReasonSegment(reason));
  const folded = message.foldedMessages ?? 0;
  // Messages, not turns: the backend counts `ModelMessage`s (a plain exchange is two, a
  // tool-heavy turn many more) and doesn't count turns at fold time, so calling them
  // turns would overstate every fold.
  if (folded > 0)
    parts.push(`${folded} ${folded === 1 ? "Message" : "Messages"} FOLDED`);
  const before = message.tokensBefore ?? 0;
  const after = message.tokensAfter ?? 0;
  // *What the fold replaced → what replaced it*, not "context before/after": `tokensAfter`
  // is the summary alone and excludes whatever tail the backend retained past the boundary.
  if (before > 0 || after > 0)
    parts.push(`${approxTokens(before)} → ${approxTokens(after)}`);
  return parts;
}

export function compactionLabel(message: ChatMessage): string {
  return compactionLabelParts(message).join(" · ");
}
