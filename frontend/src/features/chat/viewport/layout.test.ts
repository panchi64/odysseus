/** The layout over the *real* registry.
 *
 *  `paneTree.test.ts` proves the geometry against synthetic surfaces, which is the right
 *  place for the rules. This proves the wiring: that the surfaces the app actually ships
 *  are declared with the shapes the layout then files them under. A plan declared as a
 *  panel by mistake is a five-row list handed half the viewport, and nothing in the pure
 *  tests can see it because they never look at the registry.
 */

import { describe, expect, test } from "bun:test";
import {
  closeSurface,
  emptyLayout,
  hasSurface,
  isEmpty,
  isSurfaceId,
  openSurface,
  panelSurfacesOf,
  pruneLayout,
  surfacesOf,
  toggleSurface,
} from "./layout";
import { SURFACE_IDS, shapeOf } from "./surfaces";

describe("the shipped surfaces", () => {
  test("every id is recognised, and nothing else is", () => {
    for (const id of SURFACE_IDS) expect(isSurfaceId(id)).toBe(true);
    expect(isSurfaceId("nonsense")).toBe(false);
  });

  test("a plan is a strip and a view is a panel", () => {
    expect(shapeOf("plan")).toBe("strip");
    expect(shapeOf("view")).toBe("panel");
  });
});

describe("filing a surface by its shape", () => {
  test("a strip lands in the strips, not the panel region", () => {
    const layout = openSurface(emptyLayout(), "plan");
    expect(layout.strips).toEqual(["plan"]);
    expect(panelSurfacesOf(layout)).toEqual([]);
  });

  test("a panel lands in the panel region", () => {
    const layout = openSurface(emptyLayout(), "view");
    expect(layout.strips).toEqual([]);
    expect(panelSurfacesOf(layout)).toEqual(["view"]);
  });

  test("the two coexist, strips first", () => {
    let layout = toggleSurface(emptyLayout(), "view");
    layout = toggleSurface(layout, "plan");
    expect(surfacesOf(layout)).toEqual(["plan", "view"]);
  });

  test("closing one leaves the other", () => {
    let layout = openSurface(openSurface(emptyLayout(), "plan"), "view");
    layout = closeSurface(layout, "view");
    expect(hasSurface(layout, "plan")).toBe(true);
    expect(isEmpty(layout)).toBe(false);
    layout = closeSurface(layout, "plan");
    expect(isEmpty(layout)).toBe(true);
  });
});

describe("a layout that outlived the code that wrote it", () => {
  test("a surface the registry no longer has is dropped", () => {
    const stale = {
      strips: ["ghost" as never],
      panels: { kind: "leaf" as const, surface: "view" as const },
    };
    const pruned = pruneLayout(stale);
    expect(pruned.strips).toEqual([]);
    expect(panelSurfacesOf(pruned)).toEqual(["view"]);
  });
});
