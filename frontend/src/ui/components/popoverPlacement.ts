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
}

export function computePlacement(opts: {
  anchor: Rect;
  /** The panel's measured size, or null before it has rendered. */
  panel: { width: number; height: number } | null;
  viewport: Viewport;
  align?: "left" | "right";
  block?: boolean;
}): Placement {
  const { anchor, panel, viewport, align, block } = opts;
  const panelH = panel?.height ?? 0;
  // In `block` mode the panel is floored at the trigger's width but free to grow past
  // it, so the edge clamps below have to reason about whichever is actually wider —
  // using the trigger's width alone would let a content-sized panel hang off-screen.
  const measuredW = panel?.width ?? 0;
  const panelW = block ? Math.max(anchor.width, measuredW) : measuredW;

  const below = viewport.height - anchor.bottom - GAP - EDGE;
  const above = anchor.top - GAP - EDGE;
  // Flip only when below genuinely can't hold it *and* above is roomier — a panel
  // that fits below stays below even when above happens to be larger.
  const flip = panelH > below && above > below;

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
  };
}
