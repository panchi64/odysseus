import { type JSX } from "solid-js";
import { Disclosure, Divider, Stack, Text } from "~/ui";
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
 *  The label states what the fold cost, because "CONTEXT COMPACTED" alone doesn't say
 *  whether that was two messages or forty. Two things about the numbers:
 *  **messages, not turns** — the backend counts `ModelMessage`s (a plain exchange is
 *  two, a tool-heavy turn many more) and doesn't count turns at fold time, so calling
 *  them turns would overstate the fold; and the token pair reads *what the fold
 *  replaced → what replaced it*, **not** "context before/after" — `tokensAfter` is the
 *  summary alone and excludes any tail the backend retained past the boundary. Both
 *  are coarse char-based estimates, hence `~`. The backend always sends all three, so
 *  each segment is guarded on `> 0` rather than on presence.
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
      ? `${n} ${n === 1 ? "MESSAGE" : "MESSAGES"} FOLDED`
      : undefined;
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
          {["CONTEXT COMPACTED", folded(), delta()].filter(Boolean).join(" · ")}
        </Text>
        <Divider class="flex-1" />
      </div>
      {/* Names what the dimming above means. The transcript keeps every turn; only
          the model's view narrows, and that distinction is the whole point. */}
      <Text variant="micro" tone="dim" class="text-center">
        The model no longer reads the dimmed turns above — it reads this summary
        instead. Your transcript keeps all of them.
      </Text>
      <Disclosure label="SUMMARY" triggerClass="w-full">
        <Text variant="body" tone="dim" class="whitespace-pre-wrap">
          {m().content}
        </Text>
      </Disclosure>
    </Stack>
  );
}
