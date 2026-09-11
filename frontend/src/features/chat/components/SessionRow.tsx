import { Show, type JSX } from "solid-js";
import {
  Button,
  Icon,
  LedEdge,
  REVEAL_ON_GROUP_HOVER,
  Text,
  TypewriterText,
  cx,
  type ContextMenuTriggerProps,
  type LedTone,
} from "~/ui";
import { REVEAL_SPEED_MS } from "../data";
import type { ChatActivity } from "../model";

export interface SessionRowProps {
  title: string;
  selected?: boolean;
  pinned?: boolean;
  /** A freshly auto-generated title to type out in place of the static one. The
   *  header owns clearing the reveal; the row just mirrors it while it lasts. */
  reveal?: string;
  /** The backend's status for this thread's live run, when it has one. Lights the
   *  accent edge; absent leaves the row at rest. */
  activity?: ChatActivity;
  onOpen: () => void;
  /** Open this row's menu at the cursor. The whole row is the target. */
  onContextMenu: (e: MouseEvent) => void;
  /** ARIA and click wiring for the "···". Spread it rather than rebuilding it, so the
   *  expanded state travels with the handler that changes it. */
  menuTrigger: ContextMenuTriggerProps;
  /** True while *this* row's menu is showing. */
  menuOpen?: boolean;
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
 * A selectable session row with its own actions menu.
 *
 * **Two ways into one menu.** A right-click anywhere on the row opens it at the cursor;
 * the "···" opens the same menu against the button. Right-click is the faster gesture
 * and the one a list invites, but it is invisible and unreachable from a keyboard, so
 * the button is what makes the actions discoverable and operable. Neither alone is the
 * whole control.
 *
 * The row used to carry a pin toggle and a `3D AGO` stamp. Pinning moved into the menu
 * and the stamp into the heading above the run — it answered "when" once per row, in a
 * column the eye had to visit for all of them, to separate threads mostly from the same
 * week. What is left of the pin is a **marker, not a control**: in a sandbox mode the
 * `Pinned` heading already says it, but a code thread is filed under its directory and
 * would otherwise float to the top of its section for no visible reason.
 *
 * The label and the "···" are sibling buttons (not nested) so neither swallows the
 * other's click.
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
      // On the row's own element, not the label button: the target is the whole row,
      // including the strip the "···" sits on and the padding around it. A right-click
      // that lands two pixels off the label and does nothing reads as the menu being
      // broken rather than as having missed.
      onContextMenu={(e) => props.onContextMenu(e)}
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
      </button>
      {/* Marker, not a control — inside the row's own gutter so it cannot be
          mistaken for the button beside it. `sr-only` text because the glyph is
          the only thing carrying the state (§12). */}
      <Show when={props.pinned}>
        <Icon name="pin" size={12} class="shrink-0 text-dim" />
        <span class="sr-only">pinned</span>
      </Show>
      <Button
        {...props.menuTrigger}
        variant="ghost"
        size="sm"
        aria-label="Thread actions"
        // Held visible while this row's own menu is open. `REVEAL_ON_GROUP_HOVER`
        // covers hover, focus and touch, but the panel is portalled to the body — so
        // the moment it opens, focus leaves the row, `focus-within` stops holding, and
        // the trigger fades out from under the menu it just opened.
        class={cx("shrink-0", !props.menuOpen && REVEAL_ON_GROUP_HOVER)}
      >
        ···
      </Button>
    </LedEdge>
  );
}
