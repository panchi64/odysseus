import { Show, type JSX } from "solid-js";
import { Icon, Text } from "~/ui";
import type { WorkShape } from "../workShape";
import { ProcessRow, Sep } from "./ProcessRow";

/** The collapsed work log's own line: the last thing the run did, and how big it
 *  is.
 *
 *  **It is deliberately the same sentence its rows are.** `glyph · Label ·
 *  detail` is `ToolCallCard`'s anatomy exactly, so the fold reads as its own
 *  most recent row wearing a chevron rather than as a third species of line on a
 *  rail that already has two. That is most of the legibility win: the operator
 *  parses one shape down the whole column instead of switching grammars at every
 *  fold.
 *
 *  What it replaced was `Read ×4 · Web search · +2 · Reasoning ×3`. Naming the
 *  tools was right; tallying them was not. A per-tool count is a magnitude with
 *  nothing to attach to — four reads and seven reads are the same decision — and
 *  `+2` was a count of kinds deliberately withheld, which is the least useful
 *  thing a summary can say. `Read agent.py` is the same pixels carrying a noun.
 *
 *  It also moves while the turn runs. Settled work keeps folding in as the run
 *  advances, so this line steps forward with it — the fold's own proof of life,
 *  snapping rather than easing, in the machine's register (§8). No throbber sits
 *  here: nothing *inside* a fold is ever live (`isCollapsible` pins a call in
 *  flight, an open approval and a failure inline), so a spinner on this row
 *  would point at finished work. `TurnProgressRail` is where the live phase is
 *  spoken, once.
 *
 *  The step count is the run's size, dim and pinned right where a card puts its
 *  elapsed figure — metadata, not the headline. "Is opening this worth it" is
 *  the one question a bare magnitude does answer honestly. */
export function WorkLogHeader(props: {
  shape: WorkShape;
  open: boolean;
  onToggle: () => void;
}): JSX.Element {
  const latest = () => props.shape.latest;
  return (
    <ProcessRow
      open={props.open}
      onToggle={props.onToggle}
      label="Work log"
      trailing={
        <Show when={props.shape.steps > 0}>
          <Text variant="micro" tone="dim" class="tabular-nums">
            {`${props.shape.steps} steps`}
          </Text>
        </Show>
      }
    >
      <Show when={latest()}>
        {(step) => (
          <>
            <Sep />
            <Icon name={step().icon} size={12} class="shrink-0 text-dim" />
            <Text variant="micro" tone="default" class="shrink-0">
              {step().label}
            </Text>
            {/* The only segment allowed to shrink, and the only one that should:
                a truncated path is still recognizable, a truncated verb is not
                (the same rule `ProcessRow` documents for its own label). */}
            <Show when={step().detail}>
              {(detail) => (
                <>
                  <Sep />
                  <Text variant="micro" tone="dim" class="min-w-0 truncate">
                    {detail()}
                  </Text>
                </>
              )}
            </Show>
          </>
        )}
      </Show>
    </ProcessRow>
  );
}
