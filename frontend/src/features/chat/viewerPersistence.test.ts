/** The viewport panel's width rules.
 *
 *  Two panels share one slot and want very different sizes, and the slot has to fit
 *  inside a row that the shell can resize under it. That makes three rules worth
 *  pinning: each panel keeps its own width, a width is clamped when it is *read*
 *  rather than when it is stored, and the row's bound outranks both the ceiling and
 *  the browser's floor.
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
    setAvailableWidth(3000); // wide enough that only the floors and the cap bind
  });

  test("each panel has its own floor", () => {
    // A narrow column is fine for a document; a 1280×800 page frame in one is a
    // thumbnail, so the browser's floor is well above the View's.
    expect(clampWidth(100, "view")).toBe(320);
    expect(clampWidth(100, "browser")).toBe(640);
  });

  test("the ceiling is the row's, not the cap", () => {
    // 1600 − 480 of transcript = 1120, which is *under* the 1200 cap: if the row
    // bound were dropped, this would come back 1200.
    setAvailableWidth(1600);
    expect(clampWidth(5000, "view")).toBe(1120);
    // Wide enough that the cap is the binding constraint again.
    setAvailableWidth(3000);
    expect(clampWidth(5000, "view")).toBe(1200);
  });

  test("the browser's floor gives way to the row", () => {
    // 1000 − 480 = 520, under the browser's 640 floor. The panel takes what there is
    // rather than pushing the transcript past its min-content and the row past the
    // shell — which is exactly what clamping against the window instead did.
    setAvailableWidth(1000);
    expect(clampWidth(900, "browser")).toBe(520);
  });

  test("the two panels remember separate widths", () => {
    setPanelWidth("browser", 900);
    expect(panelWidth("browser")).toBe(900);
    // Untouched by the browser's drag — the View comes back to its own width when the
    // session ends.
    expect(panelWidth("view")).toBe(384);
  });

  test("a width set on a wide row survives a narrow one", () => {
    setPanelWidth("browser", 1100);
    setAvailableWidth(1000);
    expect(panelWidth("browser")).toBe(520); // clamped on read…
    setAvailableWidth(3000);
    expect(panelWidth("browser")).toBe(1100); // …not trimmed in storage
  });
});
