import { describe, expect, test } from "bun:test";
import { computePlacement, EDGE, GAP, type Rect } from "./popoverPlacement";

const VIEWPORT = { width: 1000, height: 800 };

/** A trigger at a given vertical position. Width/height are a plausible button. */
function anchorAt(top: number, left = 400): Rect {
  return {
    top,
    bottom: top + 24,
    left,
    right: left + 80,
    width: 80,
    height: 24,
  };
}

const PANEL = { width: 160, height: 200 };

describe("vertical placement", () => {
  test("sits below the trigger when there is room", () => {
    const anchor = anchorAt(100);
    const p = computePlacement({ anchor, panel: PANEL, viewport: VIEWPORT });
    expect(p.top).toBe(anchor.bottom + GAP);
  });

  test("flips above when the panel would run off the bottom", () => {
    // 700 + 24 leaves ~68px below for a 200px panel: the reported bug.
    const anchor = anchorAt(700);
    const p = computePlacement({ anchor, panel: PANEL, viewport: VIEWPORT });
    expect(p.top).toBe(anchor.top - GAP - PANEL.height);
    expect(p.top).toBeLessThan(anchor.top);
  });

  test("stays below when it fits, even though above is roomier", () => {
    // Deliberately adversarial: at top=500 there is 264px below (the 200px panel
    // fits) but 488px above. A naive "pick the roomier side" rule flips here and is
    // wrong to — the panel should not move when it doesn't have to.
    const anchor = anchorAt(500);
    const p = computePlacement({ anchor, panel: PANEL, viewport: VIEWPORT });
    expect(p.top).toBe(anchor.bottom + GAP);
  });

  test("never lets a flipped panel escape the top edge", () => {
    const anchor = anchorAt(40);
    const tall = { width: 160, height: 600 };
    const p = computePlacement({ anchor, panel: tall, viewport: VIEWPORT });
    expect(p.top).toBeGreaterThanOrEqual(EDGE);
  });
});

describe("clamping", () => {
  test("does not clamp a panel that fits — the caller's own max-h must win", () => {
    // The regression this guards: an unconditional inline max-height overrides
    // Combobox's max-h-80 and Select's max-h-72, making every dropdown window-tall.
    const p = computePlacement({
      anchor: anchorAt(100),
      panel: PANEL,
      viewport: VIEWPORT,
    });
    expect(p.clampHeight).toBeNull();
  });

  test("clamps to the room available when nothing fits either way", () => {
    const anchor = anchorAt(380); // roughly centered — neither side holds 600px
    const tall = { width: 160, height: 600 };
    const p = computePlacement({ anchor, panel: tall, viewport: VIEWPORT });
    expect(p.clampHeight).not.toBeNull();
    expect(p.clampHeight!).toBeLessThan(tall.height);
    expect(p.clampHeight!).toBeGreaterThan(0);
  });
});

describe("horizontal placement", () => {
  test("aligns left by default and right on request", () => {
    const anchor = anchorAt(100, 400);
    expect(
      computePlacement({ anchor, panel: PANEL, viewport: VIEWPORT }).left,
    ).toBe(anchor.left);
    expect(
      computePlacement({
        anchor,
        panel: PANEL,
        viewport: VIEWPORT,
        align: "right",
      }).left,
    ).toBe(anchor.right - PANEL.width);
  });

  test("shifts back inside the right edge", () => {
    const anchor = anchorAt(100, 960); // a trigger hard against the right edge
    const p = computePlacement({ anchor, panel: PANEL, viewport: VIEWPORT });
    expect(p.left + PANEL.width).toBeLessThanOrEqual(VIEWPORT.width - EDGE);
  });

  test("shifts back inside the left edge", () => {
    const anchor = anchorAt(100, 2);
    const p = computePlacement({
      anchor,
      panel: PANEL,
      viewport: VIEWPORT,
      align: "right",
    });
    expect(p.left).toBeGreaterThanOrEqual(EDGE);
  });

  test("a panel wider than the viewport still starts on-screen", () => {
    const anchor = anchorAt(100, 400);
    const wide = { width: 1200, height: 100 };
    const p = computePlacement({ anchor, panel: wide, viewport: VIEWPORT });
    // Not negative: the max-outermost clamp is what guarantees this.
    expect(p.left).toBe(EDGE);
  });
});

describe("block mode", () => {
  test("floors the panel at the trigger width and ignores align", () => {
    const anchor = anchorAt(100, 300);
    const p = computePlacement({
      anchor,
      panel: PANEL,
      viewport: VIEWPORT,
      align: "right",
      block: true,
    });
    expect(p.minWidth).toBe(anchor.width);
    expect(p.left).toBe(anchor.left);
  });

  test("never pins a panel down to a narrower trigger", () => {
    // The reported bug: the composer's mode select is sized by its own short label,
    // so a panel pinned to it truncated every option. `minWidth` is a floor — the
    // 160px panel above an 80px trigger keeps its own width.
    const anchor = anchorAt(100, 300); // 80px wide
    const p = computePlacement({
      anchor,
      panel: PANEL, // 160px wide
      viewport: VIEWPORT,
      block: true,
    });
    expect(p.minWidth!).toBeLessThanOrEqual(PANEL.width);
  });

  test("keeps a content-sized panel inside the right edge", () => {
    // The clamp has to reason about the panel's real width, not the trigger's: a
    // narrow trigger near the edge with a wide menu used to hang off-screen.
    const anchor = anchorAt(100, 940); // 80px trigger hard against the right edge
    const p = computePlacement({
      anchor,
      panel: PANEL, // twice the trigger's width
      viewport: VIEWPORT,
      block: true,
    });
    expect(p.left + PANEL.width).toBeLessThanOrEqual(VIEWPORT.width - EDGE);
  });
});

describe("first pass, before the panel has rendered", () => {
  test("places below without flipping on a zero-height panel", () => {
    const anchor = anchorAt(700);
    const p = computePlacement({ anchor, panel: null, viewport: VIEWPORT });
    expect(p.top).toBe(anchor.bottom + GAP);
    expect(p.clampHeight).toBeNull();
  });
});
