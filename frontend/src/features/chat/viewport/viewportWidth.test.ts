/** The panel's width arithmetic.
 *
 *  The panel shares a row the shell can resize under it, and holds a set of surfaces whose
 *  minimums it has to respect. Four rules are worth pinning: a width is clamped when it is
 *  *read* rather than when it is stored, the row's bound outranks both the ceiling and the
 *  floor, the floor is derived from what is open rather than remembered per surface, and
 *  widening for an arriving surface happens once and never downward.
 *
 *  The row's bound is injected (`setAvailableWidth`) rather than read off `window`, which
 *  is what makes any of it testable — and is load-bearing in the app for the same reason:
 *  the row is not the window.
 *
 *  `localStorage` does not exist under `bun test`, so it is stubbed before the module is
 *  imported; the width store reads its seed at module scope.
 */

import { beforeEach, describe, expect, test } from "bun:test";

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
}
(globalThis as { localStorage?: unknown }).localStorage = new MemoryStorage();

const {
  clampWidth,
  floorFor,
  panelWidth,
  restingWidthFor,
  setAvailableWidth,
  setPanelWidth,
  widenFor,
} = await import("./viewportWidth");

describe("clamping", () => {
  beforeEach(() => {
    setAvailableWidth(3000); // wide enough that only the floor and the cap bind
    setPanelWidth(384, []);
  });

  test("a narrow request is held at the floor", () => {
    expect(clampWidth(100)).toBe(320);
  });

  test("the ceiling is the row's, not the cap", () => {
    // 1600 − 480 of transcript = 1120, which is *under* the 1200 cap: if the row
    // bound were dropped, this would come back 1200.
    setAvailableWidth(1600);
    expect(clampWidth(5000)).toBe(1120);
    setAvailableWidth(3000);
    expect(clampWidth(5000)).toBe(1200);
  });

  test("a row with nothing to spare still leaves the panel its minimum", () => {
    setAvailableWidth(500);
    expect(clampWidth(5000)).toBe(320);
  });

  test("a stored width is clamped on read, not on store", () => {
    setPanelWidth(900, []);
    setAvailableWidth(1000); // 1000 − 480 = 520
    expect(panelWidth()).toBe(520);
    // The preference itself survived the narrow session.
    setAvailableWidth(3000);
    expect(panelWidth()).toBe(900);
  });
});

describe("the floor the open set imposes", () => {
  beforeEach(() => setAvailableWidth(3000));

  test("nothing open falls back to the bare minimum", () => {
    expect(floorFor([])).toBe(320);
  });

  test("a strip imposes nothing — only panels are tiled", () => {
    expect(floorFor(["tasks"])).toBe(320);
  });

  test("the widest open panel sets it", () => {
    expect(floorFor(["view"])).toBe(320);
  });

  test("a request under the floor is lifted to it", () => {
    expect(clampWidth(100, ["view"])).toBe(320);
  });

  test("the row's ceiling still outranks the floor", () => {
    // A row with almost nothing to spare cannot be made wider by what is open.
    setAvailableWidth(500);
    expect(clampWidth(1000, ["view"])).toBe(320);
  });
});

describe("widening for an arriving surface", () => {
  beforeEach(() => {
    setAvailableWidth(3000);
    setPanelWidth(320, []);
  });

  test("a narrower panel grows to the arriving surface's resting width", () => {
    expect(restingWidthFor(["view"])).toBe(384);
    expect(widenFor(["view"])).toBe(true);
    expect(panelWidth(["view"])).toBe(384);
  });

  test("it never shrinks a panel the operator has widened", () => {
    setPanelWidth(900, []);
    expect(widenFor(["view"])).toBe(false);
    expect(panelWidth(["view"])).toBe(900);
  });

  test("it does not ratchet on repeated arrivals", () => {
    widenFor(["view"]);
    const settled = panelWidth(["view"]);
    widenFor(["view"]);
    widenFor(["view"]);
    expect(panelWidth(["view"])).toBe(settled);
  });
});
