import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

/** Which accent the edge emits when lit. Defaults to `info` — the tone the
 *  system already uses for "live data / in flight". */
export type LedTone = "info" | "nominal" | "warn" | "alert" | "accent";

/* `info` needs no class: `.ody-led` sets `--led` to the info accent itself, so
   the default costs nothing. The rest override it. */
const toneClass: Record<LedTone, string> = {
  info: "",
  nominal: "ody-led-nominal",
  warn: "ody-led-warn",
  alert: "ody-led-alert",
  accent: "ody-led-accent",
};

export interface LedEdgeProps extends JSX.HTMLAttributes<HTMLDivElement> {
  /** Light the edge. When false it renders the plain `line` hairline, so a
   *  region can sit in a timeline unlit and light up without reflowing. */
  lit?: boolean;
  tone?: LedTone;
  /** Layout glue — padding, spacing, flex. The component owns only the edge. */
  class?: string;
  children: JSX.Element;
}

/**
 * A container whose **left edge is a hairline that can be lit** — an LED strip
 * spilling light onto the surface beside it, rather than a border that merely
 * changes colour.
 *
 * This is the system's way of saying *"this region is live right now"*: a
 * streaming block in the chat timeline, a running task, an active pane. It reads
 * as an emitter because the glow is directional — four shadow layers pushed
 * left with a long falloff (see `.ody-led` in theme.css). A symmetric glow would
 * read as a halo around a line, which is not what an LED does.
 *
 * Two properties make it safe to toggle on live content:
 * - **The rule never changes width.** Lit and unlit are both `--line-w`; the
 *   border stays in the box model while lit (transparent, with the LED's own bar
 *   painted over it), so lighting a region shifts nothing around it.
 * - **The glow is a shadow**, so it costs no layout and cannot push siblings.
 *
 * One caveat worth knowing: the bloom reaches ~90px to the left, and **any
 * ancestor with `overflow` other than `visible` clips it at its padding box**.
 * A lit region inside a scroll container needs horizontal padding on that
 * container for the light to spill into, or the glow is cut off flush against
 * the rule and reads as a hard coloured border again.
 */
export function LedEdge(props: LedEdgeProps): JSX.Element {
  const [local, rest] = splitProps(props, ["lit", "tone", "class", "children"]);
  return (
    <div
      class={cx(
        // The border stays in the box model in BOTH states — transparent while
        // lit, where the LED's own bar paints over it. Without that the element
        // would lose its border on lighting up and nudge its contents sideways.
        "border-l",
        local.lit
          ? cx("ody-led border-transparent", toneClass[local.tone ?? "info"])
          : "border-line",
        local.class,
      )}
      {...rest}
    >
      {local.children}
    </div>
  );
}
