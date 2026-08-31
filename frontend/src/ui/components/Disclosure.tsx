import { createSignal, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";
import { Collapse } from "./Collapse";

/** Which glyph says "there is more under here".
 *
 *  A chevron reads as *direction* — fine on a heading that is only a heading, wrong
 *  beside anything that could be navigated to, where it reads as "go there". The
 *  registration-crosshair plus/minus can't be misread, so it is what the rail's area
 *  headers and the thread list's workspace headings use. */
export type DisclosureMarker = "chevron" | "plusminus";

/** The glyph beside a label. A plus needs a touch more than a chevron to read as a
 *  plus at all, hence the two sizes. */
const MARKER_SIZE: Record<DisclosureMarker, number> = {
  chevron: 12,
  plusminus: 14,
};

/** A lone toggle is the control rather than an ornament on one, so it gets the
 *  larger glyph and a target to go with it. */
const TOGGLE_SIZE = 16;

function markerName(
  marker: DisclosureMarker,
  open: boolean,
): "chevron-down" | "chevron-right" | "minus" | "plus" {
  if (marker === "plusminus") return open ? "minus" : "plus";
  return open ? "chevron-down" : "chevron-right";
}

export interface DisclosureProps {
  /** Sentence-case label shown beside the marker — this is the interface
   *  naming a section, so it takes the sans voice (§2), not the old uppercase. */
  label: string;
  /** Controlled open state. Omit to let the component own it. */
  open?: boolean;
  /** Toggle handler. Required when `open` is supplied. */
  onToggle?: () => void;
  /** Initial state when uncontrolled. Defaults to closed. */
  defaultOpen?: boolean;
  /** Which glyph leads the trigger. Defaults to the chevron. */
  marker?: DisclosureMarker;
  /** Rendered inside the trigger after the label — a peek line, a count, a status
   *  glyph. */
  trailing?: JSX.Element;
  /** Extra classes for the trigger row (e.g. `w-full` for a full-width header). */
  triggerClass?: string;
  /** Body wrapper classes. Replaces the default spacing rather than adding to it,
   *  so a caller can set its own margin without two competing utilities. */
  class?: string;
  children: JSX.Element;
}

/**
 * A labelled show/hide section — marker, label, collapsing body.
 *
 * The look is the one the chat surface's own collapsibles converged on: a small glyph
 * that flips on open, a dim label that brightens on hover, and the body beneath. Works
 * controlled (pass `open` + `onToggle`) or uncontrolled.
 *
 * **The body opens over its own height** (`Collapse`) rather than appearing outright.
 * Content that simply vanishes takes everything below it with it, which is the single
 * most common reason a screen reads as having redrawn — and a disclosure is the exact
 * case that rule is written for.
 *
 * The plus/minus `marker` is what lets the rail's area headers and the thread list's
 * workspace headings live here instead of hand-rolling a header each. Both used to, and
 * the copies had already drifted apart on the accessible name and on which parts of the
 * row take the hover fill.
 *
 * One shape still can't be this component: the nav rail's header is a *link* with the
 * toggle beside it (a button inside a link is invalid HTML, the same reason `ListRow`'s
 * `right` slot is a span). `DisclosureToggle` is that control on its own, so even the
 * exception shares the aria and the paint.
 *
 * `ToolCallCard` and its siblings also stay off this: their trigger row carries a whole
 * cluster of controls, and covering that would mean prop-configuring arbitrary trigger
 * children, at which point the component stops being simpler than the markup it hides.
 * They share `ProcessRow` instead.
 */
export function Disclosure(props: DisclosureProps): JSX.Element {
  const [uncontrolled, setUncontrolled] = createSignal(
    props.defaultOpen ?? false,
  );
  const isOpen = (): boolean => props.open ?? uncontrolled();
  const marker = (): DisclosureMarker => props.marker ?? "chevron";
  const toggle = (): void => {
    if (props.open === undefined) setUncontrolled((v) => !v);
    props.onToggle?.();
  };

  return (
    <div>
      <button
        type="button"
        aria-expanded={isOpen()}
        onClick={(e) => {
          // Trigger clicks stop here: a disclosure nested inside its own clickable
          // wrapper would otherwise toggle twice and appear inert.
          e.stopPropagation();
          toggle();
        }}
        class={cx(
          "flex items-center gap-1 text-left text-dim transition-colors hover:text-text",
          props.triggerClass,
        )}
      >
        <Icon
          name={markerName(marker(), isOpen())}
          size={MARKER_SIZE[marker()]}
          class="shrink-0"
        />
        {/* Truncating, always. A section's name is whatever it is named — a
            workspace heading is a directory path — and a header that cannot
            overflow its own trigger is the only version of this that is safe to
            hand an arbitrary label. */}
        <Text variant="label" tone="dim" class="min-w-0 truncate">
          {props.label}
        </Text>
        {props.trailing}
      </button>
      <Collapse open={isOpen()}>
        <div class={props.class ?? "mt-2"}>{props.children}</div>
      </Collapse>
    </div>
  );
}

export interface DisclosureToggleProps {
  open: boolean;
  onToggle: () => void;
  /** What the section is called — the toggle carries no visible text, so this is
   *  the whole of its accessible name ("Expand Research"). */
  label: string;
  class?: string;
}

/** The plus/minus control by itself, for the one header that cannot be a single
 *  button (see `Disclosure`). It owns the accessible name and the hover paint so the
 *  exception cannot drift from the rule. */
export function DisclosureToggle(props: DisclosureToggleProps): JSX.Element {
  return (
    <button
      type="button"
      aria-expanded={props.open}
      aria-label={`${props.open ? "Collapse" : "Expand"} ${props.label}`}
      onClick={props.onToggle}
      class={cx(
        "flex size-7 shrink-0 items-center justify-center text-dim transition-colors hover:bg-raised hover:text-text",
        props.class,
      )}
    >
      <Icon name={markerName("plusminus", props.open)} size={TOGGLE_SIZE} />
    </button>
  );
}
