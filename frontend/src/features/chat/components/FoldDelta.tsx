import { type JSX } from "solid-js";
import { Stack, Text } from "~/ui";
import { approxTokens } from "../compactionLabel";
import { StackedBar } from "./StackedBar";

/** What the fold replaced, against what replaced it.
 *
 *  The divider's label already reports `~62k → ~4k`, and two numbers with an arrow
 *  between them are a fact the operator has to do arithmetic on before it means anything.
 *  The same pair drawn to scale is the one reading that does not need arithmetic: a long
 *  bar over a short one *is* the reclaimed room.
 *
 *  **Both bars share a denominator — the larger of the two figures — so the shorter one
 *  is short.** Giving each its own scale would draw two full-width bars and say the
 *  opposite of what happened, which is the same mistake the context gauge avoids by
 *  drawing every row against the window rather than against what is used.
 *
 *  Estimates, not billing figures: the backend measures both ends with the coarse
 *  char-based proxy the compaction trigger itself uses, which is why every number here
 *  wears a `~`. Deliberately *not* a percentage — a fold's value is the room it freed,
 *  and "93.4% reduction" invites a precision the estimate does not have.
 */
export function FoldDelta(props: {
  /** Coarse token estimate over the messages that were folded. */
  before: number;
  /** Coarse token estimate over the summary that replaced them. */
  after: number;
}): JSX.Element {
  // The larger figure is the full width. `|| 1` guards the all-zero case rather than
  // dividing by nothing; the caller already declines to render that, so this is only
  // making the arithmetic total.
  const scale = () => Math.max(props.before, props.after) || 1;
  const share = (n: number) => Math.min(100, (n / scale()) * 100);
  return (
    <Stack gap={2}>
      <Row
        label="Replaced"
        tokens={props.before}
        share={share(props.before)}
        // The heavier step for what was spent, the brightest for what is still being
        // carried — the same ordering the context breakdown uses, where the brightest
        // row is the one the operator can still act on.
        fill="bg-text"
      />
      <Row
        label="Now"
        tokens={props.after}
        share={share(props.after)}
        fill="bg-bright"
      />
    </Stack>
  );
}

function Row(props: {
  label: string;
  tokens: number;
  share: number;
  fill: string;
}): JSX.Element {
  return (
    <Stack gap={1}>
      <div class="flex items-baseline justify-between gap-3">
        <Text variant="micro" tone="dim">
          {props.label}
        </Text>
        <Text variant="micro" tone="dim" class="tabular-nums">
          {approxTokens(props.tokens)}
        </Text>
      </div>
      <StackedBar
        segments={[{ key: props.label, share: props.share, fill: props.fill }]}
      />
    </Stack>
  );
}
