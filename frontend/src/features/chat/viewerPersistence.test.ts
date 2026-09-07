/** The viewport panel's width rules.
 *
 *  The panel shares a row the shell can resize under it, which makes two rules worth
 *  pinning: a width is clamped when it is *read* rather than when it is stored, and the
 *  row's bound outranks both the ceiling and the floor.
 *
 *  The bound is injected (`setAvailableWidth`) rather than read off `window`, which is
 *  what makes it testable here at all — and is load-bearing in the app for the same
 *  reason it is convenient here: the row is not the window.
 */

import { beforeEach, describe, expect, test } from "bun:test";
import {
  clampWidth,
  panelWidth,
  setAvailableWidth,
  setPanelWidth,
} from "./viewerPersistence";

describe("panel width", () => {
  beforeEach(() => {
    setAvailableWidth(3000); // wide enough that only the floor and the cap bind
  });

  test("a narrow request is held at the floor", () => {
    expect(clampWidth(100)).toBe(320);
  });

  test("the ceiling is the row's, not the cap", () => {
    // 1600 − 480 of transcript = 1120, which is *under* the 1200 cap: if the row
    // bound were dropped, this would come back 1200.
    setAvailableWidth(1600);
    expect(clampWidth(5000)).toBe(1120);
    // Wide enough that the cap is the binding constraint again.
    setAvailableWidth(3000);
    expect(clampWidth(5000)).toBe(1200);
  });

  test("a row with nothing to spare still leaves the panel its minimum", () => {
    // 500 − 480 = 20, far under the floor. The transcript's reserve is a preference,
    // not a guarantee: a panel 20px wide is not a panel, so the floor stands and the
    // row overflows instead.
    setAvailableWidth(500);
    expect(clampWidth(900)).toBe(320);
  });

  test("a width set on a wide row survives a narrow one", () => {
    setPanelWidth(1100);
    setAvailableWidth(1000);
    expect(panelWidth()).toBe(520); // clamped on read…
    setAvailableWidth(3000);
    expect(panelWidth()).toBe(1100); // …not trimmed in storage
  });
});
