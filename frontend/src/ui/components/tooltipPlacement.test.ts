import { describe, expect, test } from "bun:test";
import {
  computeTipPosition,
  TIP_EDGE,
  TIP_GAP,
  type TipRect,
} from "./tooltipPlacement";

const VIEWPORT = { width: 1000, height: 800 };

/** A trigger at a given position. Width/height are a plausible inline readout. */
function anchorAt(top: number, left = 400, width = 80, height = 20): TipRect {
  return {
    top,
    bottom: top + height,
    left,
    right: left + width,
    width,
    height,
  };
}

const TIP = { width: 200, height: 40 };

describe("side selection", () => {
  test("sits on the requested side when there is room", () => {
    const anchor = anchorAt(400);
    expect(
      computeTipPosition({ anchor, tip: TIP, viewport: VIEWPORT, side: "top" })
        .side,
    ).toBe("top");
    expect(
      computeTipPosition({
        anchor,
        tip: TIP,
        viewport: VIEWPORT,
        side: "bottom",
      }).side,
    ).toBe("bottom");
  });

  test("defaults to top", () => {
    const p = computeTipPosition({
      anchor: anchorAt(400),
      tip: TIP,
      viewport: VIEWPORT,
    });
    expect(p.side).toBe("top");
  });

  test("flips to the bottom when the tip would clear the top edge", () => {
    // The composer's readout line is docked at the bottom of the window, but a tip
    // on a trigger near the TOP has nowhere above it to go.
    const anchor = anchorAt(10);
    const p = computeTipPosition({
      anchor,
      tip: TIP,
      viewport: VIEWPORT,
      side: "top",
    });
    expect(p.side).toBe("bottom");
    expect(p.top).toBe(anchor.bottom + TIP_GAP);
  });

  test("flips to the top when the tip would run off the bottom", () => {
    const anchor = anchorAt(780);
    const p = computeTipPosition({
      anchor,
      tip: TIP,
      viewport: VIEWPORT,
      side: "bottom",
    });
    expect(p.side).toBe("top");
  });

  test("flips a side tip when the requested edge has no room", () => {
    const anchor = anchorAt(400, 10);
    const p = computeTipPosition({
      anchor,
      tip: TIP,
      viewport: VIEWPORT,
      side: "left",
    });
    expect(p.side).toBe("right");
  });

  test("stays put when neither side can hold it", () => {
    // Nothing to gain by flipping — the clamp below is what keeps it on-screen.
    const anchor = anchorAt(400, 400);
    const huge = { width: 200, height: 2000 };
    const p = computeTipPosition({
      anchor,
      tip: huge,
      viewport: VIEWPORT,
      side: "top",
    });
    expect(p.side).toBe("top");
  });
});

describe("staying inside the viewport", () => {
  test("a wide tip on a trigger at the right edge shifts back inside", () => {
    // The reported bug: a tip rendered past the window rather than moving.
    const anchor = anchorAt(400, 960, 30);
    const p = computeTipPosition({ anchor, tip: TIP, viewport: VIEWPORT });
    expect(p.left + TIP.width).toBeLessThanOrEqual(VIEWPORT.width - TIP_EDGE);
    expect(p.left).toBeGreaterThanOrEqual(TIP_EDGE);
  });

  test("a wide tip on a trigger at the left edge shifts back inside", () => {
    const anchor = anchorAt(400, 4, 30);
    const p = computeTipPosition({ anchor, tip: TIP, viewport: VIEWPORT });
    expect(p.left).toBeGreaterThanOrEqual(TIP_EDGE);
  });

  test("a tip taller than the window still starts on-screen", () => {
    const anchor = anchorAt(400, 400);
    const huge = { width: 200, height: 2000 };
    const p = computeTipPosition({
      anchor,
      tip: huge,
      viewport: VIEWPORT,
      side: "top",
    });
    expect(p.top).toBeGreaterThanOrEqual(TIP_EDGE);
  });

  test("a side tip is clamped on the vertical axis too", () => {
    const anchor = anchorAt(2, 400);
    const p = computeTipPosition({
      anchor,
      tip: TIP,
      viewport: VIEWPORT,
      side: "right",
    });
    expect(p.top).toBeGreaterThanOrEqual(TIP_EDGE);
  });
});

describe("centring", () => {
  test("centres on the trigger's cross axis when there is room", () => {
    const anchor = anchorAt(400, 400);
    const p = computeTipPosition({ anchor, tip: TIP, viewport: VIEWPORT });
    expect(p.left).toBe(anchor.left + anchor.width / 2 - TIP.width / 2);
  });

  test("a side tip centres vertically", () => {
    const anchor = anchorAt(400, 400);
    const p = computeTipPosition({
      anchor,
      tip: TIP,
      viewport: VIEWPORT,
      side: "right",
    });
    expect(p.top).toBe(anchor.top + anchor.height / 2 - TIP.height / 2);
    expect(p.left).toBe(anchor.right + TIP_GAP);
  });
});

describe("first pass, before the tip has rendered", () => {
  test("places from a zero box without flipping", () => {
    const anchor = anchorAt(400);
    const p = computeTipPosition({
      anchor,
      tip: null,
      viewport: VIEWPORT,
      side: "top",
    });
    expect(p.side).toBe("top");
    expect(p.top).toBe(anchor.top - TIP_GAP);
  });
});
