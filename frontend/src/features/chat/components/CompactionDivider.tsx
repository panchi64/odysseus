import { type JSX } from "solid-js";
import { Disclosure, Divider, Stack, Text } from "~/ui";
import { compactionReasonSegment } from "../compactionReason";
import type { ChatMessage } from "../model";

/** A token count at the magnitude a reader actually compares — the divider's job is
 *  to show that the fold worked, not to audit it, and `62,431 → 4,102` buries that in
 *  digits. Under a thousand the exact number is already short enough to print. */
function approxTokens(n: number): string {
  if (n >= 1_000_000) return `~${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `~${Math.round(n / 1_000)}k`;
  return `~${n}`;
}

/** Where the thread's earlier turns were folded into a summary to free up context.
 *  A rule across the width rather than a bubble, because nobody said it — the
 *  chassis did. The summary itself is what the model now replays in place of
 *  everything above, so it is available behind a disclosure rather than hidden:
 *  it is the only way to see what the assistant still remembers.
 *
 *  The label states what the fold cost, because "Context compacted" alone doesn't say
 *  whether that was two messages or forty. Two things about the numbers:
 *  **messages, not turns** — the backend counts `ModelMessage`s (a plain exchange is
 *  two, a tool-heavy turn many more) and doesn't count turns at fold time, so calling
 *  them turns would overstate the fold; and the token pair reads *what the fold
 *  replaced → what replaced it*, **not** "context before/after" — `tokensAfter` is the
 *  summary alone and excludes any tail the backend retained past the boundary. Both
 *  are coarse char-based estimates, hence `~`. The backend always sends all three, so
 *  each segment is guarded on `> 0` rather than on presence.
 *
 *  The reason segment is the exception to that discipline and guarded on *presence*,
 *  because it genuinely can be absent: it rides the run's stream and is not stored on
 *  the checkpoint message, so a divider the operator watched appear names what caused
 *  the fold and the same divider after a reload does not. That is why it is a fourth
 *  segment rather than part of the label — the sentence has to read correctly without
 *  it. Worth carrying even so: a fold the operator asked for, one that fired at their
 *  threshold, and one the provider forced by refusing an oversized request are three
 *  different stories, and only the last means the turn nearly died.
 *
 *  Pairs with the dim pass the transcript applies above this point
 *  (`MessageItem`'s `dimmed`) — this says in words what that says at a glance. */
export function CompactionDivider(props: {
  message: ChatMessage;
}): JSX.Element {
  const m = () => props.message;
  const folded = () => {
    const n = m().foldedMessages ?? 0;
    return n > 0
      ? `${n} ${n === 1 ? "Message" : "Messages"} FOLDED`
      : undefined;
  };
  const reason = () => {
    const r = m().compactionReason;
    return r ? compactionReasonSegment(r) : undefined;
  };
  const delta = () => {
    const before = m().tokensBefore ?? 0;
    const after = m().tokensAfter ?? 0;
    // A fold whose estimate rounds to nothing on both sides has nothing to report;
    // `~0 → ~0` is a number on screen that answers no question.
    return before > 0 || after > 0
      ? `${approxTokens(before)} → ${approxTokens(after)}`
      : undefined;
  };
  return (
    <Stack gap={2} class="w-full py-3">
      <div class="flex items-center gap-3">
        <Divider class="flex-1" />
        <Text variant="label" tone="dim" class="text-center">
          {["Context compacted", reason(), folded(), delta()]
            .filter(Boolean)
            .join(" · ")}
        </Text>
        <Divider class="flex-1" />
      </div>
      {/* Names what the dimming above means. The transcript keeps every turn; only
          the model's view narrows, and that distinction is the whole point. */}
      <Text variant="micro" tone="dim" class="text-center">
        The model no longer reads the dimmed turns above — it reads this summary
        instead. Your transcript keeps all of them.
      </Text>
      <Disclosure label="Summary" triggerClass="w-full">
        <Text variant="body" tone="dim" class="whitespace-pre-wrap">
          {m().content}
        </Text>
      </Disclosure>
    </Stack>
  );
}
