/** The viewport panel's width rules.
 *
 *  Two panels share one slot and want very different sizes, and the slot itself has to
 *  live inside a window that the operator can resize under it. That makes three rules
 *  worth pinning: each panel keeps its own width, a width is clamped when it is *read*
 *  rather than when it is stored, and the window's bound outranks both the ceiling and
 *  the browser's floor.
 *
 *  The module reads `window` at import, so it is imported inside `beforeAll` with the
 *  fake in place — and the fake is torn down afterwards, since `bun test` shares one
 *  process across files and a stray `window` would change how any other module under
 *  test decides it is in a browser.
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";

type WidthApi = typeof import("./viewerPersistence");

/** The one listener the module registers, captured so a test can fire it. */
let onResize: (() => void) | undefined;
const fakeWindow = {
  innerWidth: 1600,
  addEventListener: (type: string, fn: () => void) => {
    if (type === "resize") onResize = fn;
  },
};

let api: WidthApi;
const resizeTo = (w: number): void => {
  fakeWindow.innerWidth = w;
  onResize?.();
};

beforeAll(async () => {
  (globalThis as { window?: unknown }).window = fakeWindow;
  api = await import("./viewerPersistence");
});

afterAll(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("panel width", () => {
  test("each panel has its own floor", () => {
    resizeTo(3000); // wide enough that only the floors bind
    // A narrow column is fine for a document; a 1280×800 page frame in one is a
    // thumbnail, so the browser's floor is well above the View's.
    expect(api.clampWidth(100, "view")).toBe(320);
    expect(api.clampWidth(100, "browser")).toBe(640);
  });

  test("the ceiling is the window's, not the cap", () => {
    // 1600 − 480 of transcript = 1120, which is *under* the 1200 cap: if the window
    // bound were dropped, this would come back 1200.
    resizeTo(1600);
    expect(api.clampWidth(5000, "view")).toBe(1120);
    // Wide enough that the cap is the binding constraint again.
    resizeTo(3000);
    expect(api.clampWidth(5000, "view")).toBe(1200);
  });

  test("the browser's floor gives way to the window", () => {
    // 1000 − 480 = 520, under the browser's 640 floor. The panel takes what there is
    // rather than pushing the transcript off the edge.
    resizeTo(1000);
    expect(api.clampWidth(900, "browser")).toBe(520);
  });

  test("the two panels remember separate widths", () => {
    resizeTo(3000);
    api.setPanelWidth("browser", 900);
    expect(api.panelWidth("browser")).toBe(900);
    // Untouched by the browser's drag — the View comes back to its own width when the
    // session ends.
    expect(api.panelWidth("view")).toBe(384);
  });

  test("a width set on a wide window survives a narrow one", () => {
    resizeTo(3000);
    api.setPanelWidth("browser", 1100);
    resizeTo(1000);
    expect(api.panelWidth("browser")).toBe(520); // clamped on read…
    resizeTo(3000);
    expect(api.panelWidth("browser")).toBe(1100); // …not trimmed in storage
  });
});
