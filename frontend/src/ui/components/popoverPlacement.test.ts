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

describe("cursor anchor — a zero-size rect at a point", () => {
  // What a context menu anchors to. It gets the flip and the clamp for free only if a
  // degenerate rect flows through the same rules as a real trigger, so these three
  // guard the "no new geometry" part of that as much as the geometry itself.
  function cursorAt(x: number, y: number): Rect {
    return { top: y, bottom: y, left: x, right: x, width: 0, height: 0 };
  }

  test("drops below and to the right of the cursor in open space", () => {
    const p = computePlacement({
      anchor: cursorAt(400, 100),
      panel: PANEL,
      viewport: VIEWPORT,
    });
    expect(p.top).toBe(100 + GAP);
    expect(p.left).toBe(400);
  });

  test("flips above when the cursor is near the bottom edge", () => {
    // 780 of 800: a 200px panel cannot hang below a right-click down there.
    const p = computePlacement({
      anchor: cursorAt(400, 780),
      panel: PANEL,
      viewport: VIEWPORT,
    });
    expect(p.top).toBe(780 - GAP - PANEL.height);
    expect(p.clampHeight).toBeNull();
  });

  test("clamps back inside the right edge", () => {
    const p = computePlacement({
      anchor: cursorAt(990, 100),
      panel: PANEL,
      viewport: VIEWPORT,
    });
    expect(p.left).toBe(VIEWPORT.width - PANEL.width - EDGE);
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

describe("width caps", () => {
  /** A composer-shaped anchor: a wide field rather than a small button. */
  const FIELD: Rect = {
    top: 600,
    bottom: 660,
    left: 200,
    right: 800,
    width: 600,
    height: 60,
  };
  /** Rows carrying a name and a sentence, laid out on one line. */
  const WIDE = { width: 1400, height: 280 };

  test("a panel never exceeds the viewport", () => {
    const p = computePlacement({
      anchor: anchorAt(100),
      panel: WIDE,
      viewport: VIEWPORT,
    });
    // Clamping only the left edge guarantees the panel *starts* on screen; the rest
    // still runs off the right.
    expect(p.maxWidth).toBe(VIEWPORT.width - 2 * EDGE);
  });

  test("`fit` holds the panel to the anchor", () => {
    const p = computePlacement({
      anchor: FIELD,
      panel: WIDE,
      viewport: VIEWPORT,
      block: true,
      fit: true,
    });
    expect(p.maxWidth).toBe(FIELD.width);
    // Floor and ceiling together: exactly the field, so the menu reads as the field
    // continued downwards.
    expect(p.minWidth).toBe(FIELD.width);
  });

  test("`fit` places the panel at its anchor, not at a clamped content width", () => {
    const p = computePlacement({
      anchor: FIELD,
      panel: WIDE,
      viewport: VIEWPORT,
      block: true,
      fit: true,
    });
    // The bug this pins: placing a 1400px measurement into a 1000px viewport pushes
    // `left` to EDGE, 192px to the left of the field the menu belongs to.
    expect(p.left).toBe(FIELD.left);
  });

  test("without `fit` a block panel still grows past a narrow trigger", () => {
    const narrow = anchorAt(100);
    const p = computePlacement({
      anchor: narrow,
      panel: { width: 240, height: 100 },
      viewport: VIEWPORT,
      block: true,
    });
    // `Select`'s case: a trigger sized by its own short label must not truncate the
    // options the operator opened it to read.
    expect(p.minWidth).toBe(narrow.width);
    expect(p.maxWidth).toBeGreaterThan(240);
  });
});

describe("preferred side", () => {
  const FIELD: Rect = {
    top: 600,
    bottom: 660,
    left: 200,
    right: 800,
    width: 600,
    height: 60,
  };

  test("`above` opens above even when it would also fit below", () => {
    // The whole point: a composer docked near the bottom has *some* room below, and a
    // menu that takes it sits on the readout line under the input.
    const roomy = { width: 600, height: 80 };
    const p = computePlacement({
      anchor: FIELD,
      panel: roomy,
      viewport: { width: 1000, height: 800 },
      prefer: "above",
    });
    expect(p.top).toBe(FIELD.top - GAP - roomy.height);
  });

  test("`above` falls back below when above cannot hold it and below is roomier", () => {
    const nearTop: Rect = { ...FIELD, top: 40, bottom: 100 };
    const tall = { width: 600, height: 400 };
    const p = computePlacement({
      anchor: nearTop,
      panel: tall,
      viewport: { width: 1000, height: 800 },
      prefer: "above",
    });
    expect(p.top).toBe(nearTop.bottom + GAP);
  });

  test("the default is still below", () => {
    const p = computePlacement({
      anchor: anchorAt(100),
      panel: PANEL,
      viewport: VIEWPORT,
    });
    expect(p.top).toBe(anchorAt(100).bottom + GAP);
  });
});
