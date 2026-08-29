import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";

export type PanelState = "default" | "active" | "alert";

export interface PanelProps extends JSX.HTMLAttributes<HTMLElement> {
  /** Header bar label (sentence case). Omit for a headerless panel. */
  label?: string;
  /** Right-aligned header content: status flag, count, meta. */
  meta?: JSX.Element;
  /** Emphasis state. `active` = the accent drop shadow; `alert` = its alert
   *  equivalent. Both are glows, never rings, and both are carried by the
   *  shadow, so a state change shifts no layout. */
  state?: PanelState;
  /** Remove the default body padding (for edge-to-edge content like tables). */
  flush?: boolean;
  /** Make the panel a full-height flex column whose body fills the remaining
   *  space — for content that must fill its height (an iframe, a scroll
   *  region). Pair with a height on `class` (e.g. `h-full`). */
  fill?: boolean;
  /** Draw real hairline rules: a border around the panel and a divider under
   *  the header. Off by default (§7) — separation normally comes from surface
   *  value and space, not from a line. Turn it on only when the panel hosts a
   *  ruled data grid whose outer edge the border completes. */
  bordered?: boolean;
  /** Drop the surface entirely: no fill, no shadow, no ring — the panel becomes
   *  its label and its content, sitting directly on the page.
   *
   *  For ambient regions that should read as *behind* the interface rather than
   *  as objects on it: the home page's recent-threads and in-flight lists, the
   *  system strip. They are things the operator can glance past, and giving them
   *  a card each turned the launchpad into a wall of boxes competing with the
   *  one surface that matters (the composer). Structure still comes from the
   *  label and the spacing — it just stops being a container. */
  bare?: boolean;
}

/* State is carried entirely by box-shadow, never by a border width, so
   selecting a panel cannot nudge its contents by a pixel. */
const stateShadow: Record<PanelState, string> = {
  default: "shadow-1",
  active: "shadow-accent",
  alert: "shadow-alert",
};

/** Bordered region with smoothed corners and an optional header bar (§10.2).
 *
 *  The default panel has **no border**. It reads as a distinct object through
 *  its surface value and the hairline ring folded into `shadow-1` — which is
 *  what keeps a page of panels from turning into a grid of boxes. */
export function Panel(props: PanelProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "label",
    "meta",
    "state",
    "flush",
    "fill",
    "bordered",
    "bare",
    "class",
    "children",
  ]);
  return (
    <section
      class={cx(
        "rounded-panel",
        // A bare panel takes no surface and no resting elevation — `shadow-1`
        // exists to define a surface, and there isn't one. A *state* shadow
        // still applies: `active`/`alert` are semantics, not decoration, and a
        // panel that drops its fill shouldn't go silent about being live.
        local.bare
          ? cx(
              "bg-transparent",
              local.state &&
                local.state !== "default" &&
                stateShadow[local.state],
            )
          : cx("bg-surface", stateShadow[local.state ?? "default"]),
        local.bordered && "border border-line",
        local.fill && "flex flex-col",
        local.class,
      )}
      {...rest}
    >
      <Show when={local.label || local.meta}>
        <header
          class={cx(
            "flex items-center justify-between gap-2 pb-2",
            // Card padding is the surface's, so a bare panel doesn't pay it —
            // its label sits flush with the content it names.
            !local.bare && "px-4 pt-3",
            local.bordered && "border-b border-line pb-3",
          )}
        >
          <Text variant="label" tone="dim">
            {local.label}
          </Text>
          <Show when={local.meta}>{local.meta}</Show>
        </header>
      </Show>
      <div
        class={cx(
          !local.bare &&
            !local.flush &&
            (local.label || local.meta ? "px-4 pb-4" : "p-4"),
          local.fill && "min-h-0 flex-1",
        )}
      >
        {local.children}
      </div>
    </section>
  );
}
