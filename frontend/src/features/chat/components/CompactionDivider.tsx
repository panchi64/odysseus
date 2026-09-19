import { Show, type JSX } from "solid-js";
import { Disclosure, Divider, Stack, Text } from "~/ui";
import { compactionLabel } from "../compactionLabel";
import type { ChatMessage } from "../model";
import { CompactionSummary } from "./CompactionSummary";
import { FoldDelta } from "./FoldDelta";

/** Where the thread's earlier turns were folded into a summary to free up context.
 *  A rule across the width rather than a bubble, because nobody said it — the
 *  chassis did. The summary itself is what the model now replays in place of
 *  everything above, so it is available behind a disclosure rather than hidden:
 *  it is the only way to see what the assistant still remembers.
 *
 *  The label states what the fold cost and *why it happened*, because "Context compacted"
 *  alone doesn't say whether that was two messages or forty, nor whether the operator
 *  asked for it. Which of those four facts a given fold can report is a rule rather than
 *  markup, so it lives in `compactionLabel.ts` and is unit-tested there.
 *
 *  Pairs with the dim pass the transcript applies above this point
 *  (`MessageItem`'s `dimmed`) — this says in words what that says at a glance. */
export function CompactionDivider(props: {
  message: ChatMessage;
}): JSX.Element {
  const m = () => props.message;
  return (
    <Stack gap={2} class="w-full py-3">
      <div class="flex items-center gap-3">
        <Divider class="flex-1" />
        <Text variant="label" tone="dim" class="text-center">
          {compactionLabel(m())}
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
        {/* What the fold cost, to scale. Guarded on the *pair*, exactly as
            `compactionLabelParts` guards the `~62k → ~4k` segment it draws — the label and
            the picture of it must not disagree about whether there is anything to report.
            `> 0` rather than presence, because the backend always sends both and zero
            means "nothing to report" rather than a measured nothing. */}
        <Show when={(m().tokensBefore ?? 0) > 0 || (m().tokensAfter ?? 0) > 0}>
          <div class="pb-3">
            <FoldDelta
              before={m().tokensBefore ?? 0}
              after={m().tokensAfter ?? 0}
            />
          </div>
        </Show>
        {/* The sections are the backend's parse of this very checkpoint, not a second
            reading of it here — so what the operator opens is what the model was given.
            The fallback is the pre-parse rendering, kept for a checkpoint folded before
            the parse existed and for one whose text the summarizer drifted away from:
            those degrade to plain text rather than to nothing. */}
        <Show
          when={m().summarySections?.length}
          fallback={
            <Text variant="body" tone="dim" class="whitespace-pre-wrap">
              {m().content}
            </Text>
          }
        >
          <CompactionSummary sections={m().summarySections ?? []} />
        </Show>
      </Disclosure>
    </Stack>
  );
}
