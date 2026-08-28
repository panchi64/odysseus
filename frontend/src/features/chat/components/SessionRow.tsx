import { Show, type JSX } from "solid-js";
import { Button, Text, TypewriterText, cx } from "~/ui";
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

/** The activity → accent edge mapping, matching the nav rail's split (§4 — color
 *  carries meaning only): a run parked on the operator's approval decision is a
 *  "needs YOU" signal (warn), plain in-flight work is ambient (info). */
const activityEdge: Record<ChatActivity, string> = {
  queued: "border-l-info",
  running: "border-l-info",
  awaiting_input: "border-l-warn",
};

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
 * A thread whose run is live carries an accent left edge. Every row reserves the
 * same 2px edge (transparent at rest) so lighting one can't shift the list.
 */
export function SessionRow(props: SessionRowProps): JSX.Element {
  return (
    <div
      class={cx(
        // No rule between rows (§7) — the hover fill and the rhythm are what
        // make this read as a list. The 2px left edge stays: it is the ambient
        // activity signal, and it is doing work no fill can.
        "group flex items-center rounded-ctl border-l-2 transition-colors hover:bg-raised",
        props.selected && "bg-raised",
        // Exactly one border-left-color class is ever emitted — two would leave the
        // winner to stylesheet order rather than intent.
        props.activity ? activityEdge[props.activity] : "border-l-transparent",
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
        class={cx(
          "shrink-0",
          !props.pinned &&
            "opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
        )}
      />
    </div>
  );
}
