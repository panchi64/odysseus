/** Where a popover panel goes. Pure geometry, split out from `Popover` so it can be
 *  tested without a DOM — the flip and the clamp are exactly the kind of rule that
 *  regresses silently, because the wrong answer still renders a panel. */

/** Distance between the trigger and the panel. */
export const GAP = 4;
/** Margin the panel keeps from the viewport edge. */
export const EDGE = 8;

export interface Rect {
  top: number;
  bottom: number;
  left: number;
  right: number;
  width: number;
  height: number;
}

export interface Viewport {
  width: number;
  height: number;
}

export interface Placement {
  top: number;
  left: number;
  /** Set **only** when the panel genuinely doesn't fit the space available, so it
   *  scrolls instead of running off-screen. Null otherwise, deliberately: an inline
   *  `max-height` beats any class, so applying one unconditionally would silently
   *  override each caller's own `max-h-*` (Combobox asks for `max-h-80`, Select for
   *  `max-h-72`) and make every dropdown as tall as the window. */
  clampHeight: number | null;
  /** `block` mode only: the width the panel must span **at least** — the trigger's.
   *
   *  Deliberately a floor and not a fixed width. Pinning the panel to the trigger
   *  made every option in a narrow control unreadable: the mode select in the
   *  composer's action row is sized by its own short label, so its menu inherited
   *  that width and truncated the very text the operator opened it to read. A
   *  field-width menu is the point of `block` — a menu *narrower than its own
   *  contents* never was. */
  minWidth?: number;
  /** The width the panel may **not exceed**.
   *
   *  Always at most the viewport, because a panel wider than the window has nowhere to
   *  be: clamping its left edge on-screen only guarantees that the *start* of it is
   *  visible, and the rest runs off the right.
   *
   *  `fit` narrows it further, to the anchor itself. That is for a panel that is an
   *  *extension of* its anchor rather than a dropdown hanging off it — the composer's
   *  `/` menu, whose rows carry a name and a sentence describing it and would otherwise
   *  size the panel to the longest sentence, covering the whole window including the nav
   *  rail. The opposite of what `minWidth` defends, which is why it is opt-in: a narrow
   *  trigger wants to grow, a full-width field wants to stay put. */
  maxWidth: number;
}

export function computePlacement(opts: {
  anchor: Rect;
  /** The panel's measured size, or null before it has rendered. */
  panel: { width: number; height: number } | null;
  viewport: Viewport;
  align?: "left" | "right";
  block?: boolean;
  /** Hold the panel to the anchor's width as well as floor it there — see
   *  `Placement.maxWidth`. */
  fit?: boolean;
  /** Which side of the anchor to open on when both would do. Default `"below"`. */
  prefer?: "above" | "below";
}): Placement {
  const { anchor, panel, viewport, align, block, fit, prefer } = opts;
  const panelH = panel?.height ?? 0;
  // In `block` mode the panel is floored at the trigger's width but free to grow past
  // it, so the edge clamps below have to reason about whichever is actually wider —
  // using the trigger's width alone would let a content-sized panel hang off-screen.
  const measuredW = panel?.width ?? 0;
  // The cap the panel is placed against, not merely reported: a panel held to the
  // anchor's width sits where that width puts it, and clamping a 1300px measurement into
  // the viewport instead would start it 300px to the left of the field it belongs to.
  const roomW = Math.max(0, viewport.width - 2 * EDGE);
  const maxWidth = fit ? Math.min(anchor.width, roomW) : roomW;
  const panelW = Math.min(
    block ? Math.max(anchor.width, measuredW) : measuredW,
    maxWidth,
  );

  const below = viewport.height - anchor.bottom - GAP - EDGE;
  const above = anchor.top - GAP - EDGE;
  // The preferred side is kept unless it genuinely can't hold the panel *and* the other
  // is roomier — a panel that fits where it was asked to go stays there even when the
  // other side happens to be larger.
  //
  // `prefer` exists because "below" is not universally right. A dropdown hangs off its
  // trigger, but a composer's suggestions belong above the field: the composer is docked
  // to the bottom of the window, so below is the few pixels left over, and a menu that
  // opens downwards pushes itself against the edge and covers the readout line under the
  // input. Above, it grows into the transcript, which is the space that is actually free.
  const preferAbove = prefer === "above";
  const preferredRoom = preferAbove ? above : below;
  const otherRoom = preferAbove ? below : above;
  const keepSide = !(panelH > preferredRoom && otherRoom > preferredRoom);
  const flip = preferAbove ? keepSide : !keepSide;

  const room = Math.max(0, flip ? above : below);
  const clampHeight = panelH > room ? room : null;

  const wanted = block
    ? anchor.left
    : align === "right"
      ? anchor.right - panelW
      : anchor.left;

  return {
    top: flip
      ? Math.max(EDGE, anchor.top - GAP - Math.min(panelH, room))
      : anchor.bottom + GAP,
    // Clamped into the viewport from both sides. `Math.max` runs outermost so a panel
    // wider than the window still starts on-screen rather than at a negative x.
    left: Math.max(EDGE, Math.min(wanted, viewport.width - panelW - EDGE)),
    clampHeight,
    minWidth: block ? anchor.width : undefined,
    maxWidth,
  };
}
