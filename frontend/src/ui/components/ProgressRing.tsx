import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import type { TextTone } from "../primitives/Text";

export interface ProgressRingProps {
  /** 0–100. Clamped, so a caller's rounding can't overdraw the arc. */
  value: number;
  /** Accent of the filled arc. Defaults to nominal. */
  tone?: Extract<TextTone, "nominal" | "warn" | "alert" | "info">;
  /** Outer diameter in px. Default 16 — the size that sits in a control row. */
  size?: number;
  /** Ring thickness in px. Default 2. */
  thickness?: number;
  /** Accessible name. The ring is a gauge, so it needs one — the number it draws
   *  is not in the accessibility tree. */
  label?: string;
  class?: string;
}

const arcStroke: Record<NonNullable<ProgressRingProps["tone"]>, string> = {
  nominal: "stroke-nominal",
  warn: "stroke-warn",
  alert: "stroke-alert",
  info: "stroke-info",
};

/** Determinate progress as a ring — `ProgressBar`'s round sibling, for the same
 *  mechanical, never-a-spinner reason.
 *
 *  It exists because a bar and a ring answer different questions. A bar reads as
 *  *travel* — how far through a download, a research round, an upload — and wants
 *  the horizontal room to say so. A ring reads as *fullness*, a dial against its own
 *  ceiling, and it holds that meaning at 16px in a row of controls where a bar would
 *  be a stripe with no legible scale. The context window is a fullness, and it sits
 *  in the composer's action row, so it is a ring.
 *
 *  Drawn from 12 o'clock, clockwise: the arc is read as a clock face, and starting at
 *  3 o'clock (the SVG default) makes a quarter-full ring look like it is pointing
 *  somewhere rather than measuring something. */
export function ProgressRing(props: ProgressRingProps): JSX.Element {
  const [local] = splitProps(props, [
    "value",
    "tone",
    "size",
    "thickness",
    "label",
    "class",
  ]);
  const size = () => local.size ?? 16;
  const thickness = () => local.thickness ?? 2;
  const clamped = () => Math.max(0, Math.min(100, local.value));
  // Inset by half the stroke so the ring's outer edge is the box, not its centreline —
  // otherwise the stroke is clipped by the viewBox at every thickness.
  const radius = () => (size() - thickness()) / 2;
  const circumference = () => 2 * Math.PI * radius();

  return (
    <svg
      width={size()}
      height={size()}
      viewBox={`0 0 ${size()} ${size()}`}
      role="progressbar"
      aria-valuenow={Math.round(clamped())}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={local.label}
      class={cx("shrink-0 -rotate-90", local.class)}
    >
      {/* The track is the unfilled remainder, so it is a rule and takes the rule
          colour — not a faded copy of the arc's tone, which would tint the empty
          part of the gauge amber as the thing it measures got worse. */}
      <circle
        cx={size() / 2}
        cy={size() / 2}
        r={radius()}
        fill="none"
        stroke-width={thickness()}
        class="stroke-line"
      />
      <circle
        cx={size() / 2}
        cy={size() / 2}
        r={radius()}
        fill="none"
        stroke-width={thickness()}
        stroke-linecap="butt"
        stroke-dasharray={`${circumference()}`}
        stroke-dashoffset={`${circumference() * (1 - clamped() / 100)}`}
        class={cx(
          "transition-[stroke-dashoffset]",
          arcStroke[local.tone ?? "nominal"],
        )}
      />
    </svg>
  );
}
