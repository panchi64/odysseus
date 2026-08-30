import { Show, type JSX } from "solid-js";
import {
  Button,
  LedEdge,
  REVEAL_ON_GROUP_HOVER,
  Text,
  TypewriterText,
  cx,
  type LedTone,
} from "~/ui";
import { REVEAL_SPEED_MS } from "../data";
import type { ChatActivity } from "../model";

export interface SessionRowProps {
  title: string;
  /** Right-aligned meta, e.g. relative time. */
  meta: string;
  selected?: boolean;
  pinned?: boolean;
  /** A freshly auto-generated title to type out in place of the static one. The
   *  header owns clearing the reveal; the row just mirrors it while it lasts. */
  reveal?: string;
  /** The backend's status for this thread's live run, when it has one. Lights the
   *  accent edge; absent leaves the row at rest. */
  activity?: ChatActivity;
  onOpen: () => void;
  onTogglePin: () => void;
}

/** The activity → LED tone mapping, matching the nav rail's split (§4 — color
 *  carries meaning only): a run parked on the operator's approval decision is a
 *  "needs YOU" signal (warn), plain in-flight work is ambient (info). */
const activityTone: Record<ChatActivity, LedTone> = {
  queued: "info",
  running: "info",
  awaiting_input: "warn",
};

/* The row is short and its light spills inward, so the reach is pulled well in:
   at full reach the bloom would wash the whole row flat instead of falling off
   across it, and `overflow-hidden` would be doing all the shaping. */
const LED_REACH = 0.6;

/** Screen-reader wording for each edge, so the state isn't carried by color alone. */
const activityLabel: Record<ChatActivity, string> = {
  queued: "queued",
  running: "running",
  awaiting_input: "awaiting approval",
};

/**
 * A selectable session row with an independent pin toggle. The label and the
 * pin are sibling buttons (not nested) so neither swallows the other's click.
 * The pin is revealed on hover/focus unless the row is already pinned.
 *
 * A thread whose run is live lights its leading edge, and the light falls
 * *inward* — across the row, under the title — so the row itself reads as the
 * thing that is running rather than as a row wearing a coloured border. Every
 * row reserves the rule (transparent at rest) so lighting one can't shift the
 * list.
 */
export function SessionRow(props: SessionRowProps): JSX.Element {
  return (
    <LedEdge
      lit={Boolean(props.activity)}
      tone={props.activity ? activityTone[props.activity] : undefined}
      spill="in"
      unlit="clear"
      reach={LED_REACH}
      class={cx(
        // No rule between rows (§7) — the hover fill and the rhythm are what
        // make this read as a list, and the leading edge shows only when there
        // is something to report.
        //
        // `overflow-hidden` is load-bearing, not tidiness: an inward glow blooms
        // on every axis, so unclipped it would bleed onto the rows above and
        // below and the list would look smudged rather than lit.
        "group flex items-center overflow-hidden rounded-ctl transition-colors hover:bg-raised",
        props.selected && "bg-raised",
      )}
    >
      <button
        type="button"
        onClick={() => props.onOpen()}
        class="flex min-w-0 flex-1 items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <Show
          when={props.reveal}
          fallback={
            <Text
              variant="label"
              tone={props.selected ? "bright" : "default"}
              class="truncate"
            >
              {props.title}
            </Text>
          }
        >
          {(reveal) => (
            <TypewriterText
              variant="label"
              tone={props.selected ? "bright" : "default"}
              text={reveal()}
              speed={REVEAL_SPEED_MS}
              class="truncate"
            />
          )}
        </Show>
        <Show when={props.activity}>
          {(activity) => (
            <span class="sr-only">{activityLabel[activity()]}</span>
          )}
        </Show>
        <Text variant="micro" tone="dim" class="shrink-0">
          {props.meta}
        </Text>
      </button>
      <Button
        variant="ghost"
        size="sm"
        leading="pin"
        active={props.pinned}
        aria-label={props.pinned ? "Unpin thread" : "Pin thread"}
        aria-pressed={props.pinned}
        onClick={() => props.onTogglePin()}
        class={cx("shrink-0", !props.pinned && REVEAL_ON_GROUP_HOVER)}
      />
    </LedEdge>
  );
}
