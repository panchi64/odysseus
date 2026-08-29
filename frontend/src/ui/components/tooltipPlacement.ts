/** Where a tooltip goes. Pure geometry, split out from `Tooltip` for the same reason
 *  `popoverPlacement` is split out of `Popover` — the flip and the clamp are exactly
 *  the kind of rule that regresses silently, because the wrong answer still renders a
 *  tip, just half of one off the edge of the window. */

/** Distance between the trigger and the tip. */
export const TIP_GAP = 4;
/** Margin the tip keeps from the viewport edge. */
export const TIP_EDGE = 8;

export type TipSide = "top" | "bottom" | "left" | "right";

export interface TipRect {
  top: number;
  bottom: number;
  left: number;
  right: number;
  width: number;
  height: number;
}

export interface TipSize {
  width: number;
  height: number;
}

export interface TipViewport {
  width: number;
  height: number;
}

export interface TipPosition {
  /** Viewport coordinates of the tip's top-left corner. Deliberately a resolved
   *  point rather than a point plus a CSS `transform`: the tip is positioned from
   *  its own measured size, and a transform applied afterwards would move it back
   *  out of the very edge this clamps it into. */
  top: number;
  left: number;
  /** The side actually used — the requested one, or its opposite after a flip. */
  side: TipSide;
}

const OPPOSITE: Record<TipSide, TipSide> = {
  top: "bottom",
  bottom: "top",
  left: "right",
  right: "left",
};

/** How much room a side has between the trigger and the viewport edge. */
function room(side: TipSide, anchor: TipRect, viewport: TipViewport): number {
  switch (side) {
    case "top":
      return anchor.top - TIP_GAP - TIP_EDGE;
    case "bottom":
      return viewport.height - anchor.bottom - TIP_GAP - TIP_EDGE;
    case "left":
      return anchor.left - TIP_GAP - TIP_EDGE;
    case "right":
      return viewport.width - anchor.right - TIP_GAP - TIP_EDGE;
  }
}

/** The extent the tip needs on a side's axis. */
function needed(side: TipSide, tip: TipSize): number {
  return side === "top" || side === "bottom" ? tip.height : tip.width;
}

/** Clamp a coordinate so the tip stays inside the viewport on that axis. `Math.max`
 *  runs outermost so a tip wider (or taller) than the window still starts on-screen
 *  rather than at a negative coordinate. */
function clamp(wanted: number, extent: number, limit: number): number {
  return Math.max(TIP_EDGE, Math.min(wanted, limit - extent - TIP_EDGE));
}

/** Place a tip against its trigger: flip to the opposite side when the requested one
 *  can't hold it and the opposite can, then centre on the cross axis and clamp into
 *  the viewport. */
export function computeTipPosition(opts: {
  anchor: TipRect;
  /** The tip's measured size, or null before it has rendered. */
  tip: TipSize | null;
  viewport: TipViewport;
  side?: TipSide;
}): TipPosition {
  const { anchor, viewport } = opts;
  const tip = opts.tip ?? { width: 0, height: 0 };
  const requested = opts.side ?? "top";

  // Flip only when the requested side genuinely can't hold the tip *and* the
  // opposite one can — a tip that fits where it was asked to go stays there, even
  // when the other side happens to be roomier.
  const opposite = OPPOSITE[requested];
  const flip =
    needed(requested, tip) > room(requested, anchor, viewport) &&
    needed(opposite, tip) <= room(opposite, anchor, viewport);
  const side = flip ? opposite : requested;

  switch (side) {
    case "top":
      return {
        side,
        top: Math.max(TIP_EDGE, anchor.top - TIP_GAP - tip.height),
        left: clamp(
          anchor.left + anchor.width / 2 - tip.width / 2,
          tip.width,
          viewport.width,
        ),
      };
    case "bottom":
      return {
        side,
        top: clamp(anchor.bottom + TIP_GAP, tip.height, viewport.height),
        left: clamp(
          anchor.left + anchor.width / 2 - tip.width / 2,
          tip.width,
          viewport.width,
        ),
      };
    case "left":
      return {
        side,
        top: clamp(
          anchor.top + anchor.height / 2 - tip.height / 2,
          tip.height,
          viewport.height,
        ),
        left: Math.max(TIP_EDGE, anchor.left - TIP_GAP - tip.width),
      };
    case "right":
      return {
        side,
        top: clamp(
          anchor.top + anchor.height / 2 - tip.height / 2,
          tip.height,
          viewport.height,
        ),
        left: clamp(anchor.right + TIP_GAP, tip.width, viewport.width),
      };
  }
}
