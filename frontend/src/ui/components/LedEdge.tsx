import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

/** Which accent the edge emits when lit. Defaults to `info` — the tone the
 *  system already uses for "live data / in flight". `neutral` is white light:
 *  presence without a claim about state, for a surface that is simply the point
 *  of action rather than a thing that is happening (§6 — attention is drawn by
 *  luminance, not hue). */
export type LedTone =
  "info" | "nominal" | "warn" | "alert" | "accent" | "neutral";

/** Which edge the emitter is mounted on. */
export type LedSide = "left" | "top";

/** Which way the light falls from that edge — away from the container, or into
 *  it and under its own content. */
export type LedSpill = "out" | "in";

/* `info` needs no class: `.ody-led` sets `--led` to the info accent itself, so
   the default costs nothing. The rest override it. */
const toneClass: Record<LedTone, string> = {
  info: "",
  nominal: "ody-led-nominal",
  warn: "ody-led-warn",
  alert: "ody-led-alert",
  accent: "ody-led-accent",
  neutral: "ody-led-neutral",
};

/* `left` is the base geometry in `.ody-led::before`, so it too costs nothing. */
const sideClass: Record<LedSide, string> = { left: "", top: "ody-led-top" };

/* Likewise `out` — throwing light away from the container is the base. */
const spillClass: Record<LedSpill, string> = { out: "", in: "ody-led-in" };

/* The border the strip replaces — kept in the box model in both states. */
const sideBorder: Record<LedSide, string> = {
  left: "border-l",
  top: "border-t",
};

export interface LedEdgeProps extends JSX.HTMLAttributes<HTMLDivElement> {
  /** Light the edge. When false the rule is still there — see `unlit` — so a
   *  region can sit unlit and light up without reflowing. */
  lit?: boolean;
  tone?: LedTone;
  /** What the rule looks like when it is NOT lit. `line` (default) leaves the
   *  hairline visible, for a structure that exists whether or not anything is
   *  happening on it — a process timeline's rail. `clear` makes it invisible but
   *  keeps its width, for a list where a rule on every row would be clutter
   *  (§7) and the light is the only thing that should ever show. */
  unlit?: "line" | "clear";
  /** Default `left` — the timeline rail. `top` turns the edge into a strip
   *  light above the content, spilling upward. */
  side?: LedSide;
  /** Default `out` — the light falls away from the container, onto the page
   *  beside it. `in` turns it inward, so it lands under the container's own
   *  content: a row that glows from its leading edge rather than a rail that
   *  glows onto its surroundings. An inward spill normally wants
   *  `overflow-hidden` on the container, or the glow bleeds onto its
   *  neighbours — it blooms on every axis, not just the one it travels. */
  spill?: LedSpill;
  /** How bright the glow is — a multiplier on the whole opacity curve. Default
   *  `1`. Per-instance on purpose: a strip mounted over a transcript has to
   *  throw harder than a rail beside a block, and that is a fact about where it
   *  hangs, not about the tone, so raising it here can never brighten every
   *  other LED wearing the same colour. */
  intensity?: number;
  /** How far the glow spreads — a multiplier on offset, blur and spread
   *  together, so the falloff keeps its shape instead of just getting brighter
   *  near the strip. Default `1` (~90px). */
  reach?: number;
  /** Layout glue — padding, spacing, flex. The component owns only the edge. */
  class?: string;
  children: JSX.Element;
}

/**
 * A container with **one hairline edge that can be lit** — an LED strip spilling
 * light onto the surface beside it, rather than a border that merely changes
 * colour.
 *
 * On its default `left` edge this is the system's way of saying *"this region is
 * live right now"*: a streaming block in the chat timeline, a running task, an
 * active pane. On `top` it becomes a strip light above the content, marking a
 * surface as the point of action (the chat composer) without the wide ambient
 * bloom. It reads as an emitter because the glow is directional — four shadow
 * layers pushed one way with a long falloff (see `.ody-led` in theme.css). A
 * symmetric glow would read as a halo around a line, which is not what an LED
 * does.
 *
 * Two properties make it safe to toggle on live content:
 * - **The rule never changes width.** Lit and unlit are both `--line-w`; the
 *   border stays in the box model while lit (transparent, with the LED's own bar
 *   painted over it), so lighting a region shifts nothing around it.
 * - **The glow is a shadow**, so it costs no layout and cannot push siblings.
 *
 * One caveat worth knowing: the bloom reaches ~90px past the strip, and **any
 * ancestor with `overflow` other than `visible` clips it at its padding box**.
 * A lit region inside a scroll container needs padding on that container for the
 * light to spill into, or the glow is cut off flush against the rule and reads
 * as a hard coloured border again.
 */
export function LedEdge(props: LedEdgeProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "lit",
    "tone",
    "unlit",
    "side",
    "spill",
    "intensity",
    "reach",
    "class",
    "style",
    "children",
  ]);
  const side = (): LedSide => local.side ?? "left";

  // Brightness and distance ride on the element itself rather than on a tone or
  // side class, so they are scoped to this one instance. `style` is merged
  // rather than replaced — a caller positioning the element keeps its own.
  const style = (): JSX.CSSProperties => ({
    ...(typeof local.style === "object" ? local.style : {}),
    ...(local.intensity === undefined ? {} : { "--led-gain": local.intensity }),
    ...(local.reach === undefined ? {} : { "--led-reach": local.reach }),
  });

  return (
    <div
      style={style()}
      class={cx(
        // The border stays in the box model in BOTH states — transparent while
        // lit, where the LED's own bar paints over it. Without that the element
        // would lose its border on lighting up and nudge its contents over.
        sideBorder[side()],
        local.lit
          ? cx(
              "ody-led border-transparent",
              sideClass[side()],
              spillClass[local.spill ?? "out"],
              toneClass[local.tone ?? "info"],
            )
          : local.unlit === "clear"
            ? "border-transparent"
            : "border-line",
        local.class,
      )}
      {...rest}
    >
      {local.children}
    </div>
  );
}
