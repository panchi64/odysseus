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

describe("a second panel surface", () => {
  /** A box wide and tall enough for any two of the shipped panels. */
  const room = { box: { width: 1200, height: 900 }, cap: 2 };

  test("tiles beside what is open rather than evicting it", () => {
    const one = openSurface(emptyLayout(), "view", room);
    const two = openSurface(one, "diff", room);
    expect(panelSurfacesOf(two)).toEqual(["view", "diff"]);
    expect(two.panels?.kind).toBe("split");
  });

  test("takes the region on its own when nobody measured a box", () => {
    // The documented behaviour of the no-tiling call, and the reason every live
    // caller passes a context: an arrival that opened this way would take down
    // whatever the operator was reading.
    const one = openSurface(emptyLayout(), "view");
    expect(panelSurfacesOf(openSurface(one, "diff"))).toEqual(["diff"]);
  });

  test("tabs rather than splitting when neither half would be legible", () => {
    const tight = { box: { width: 500, height: 300 }, cap: 2 };
    const two = openSurface(
      openSurface(emptyLayout(), "view", tight),
      "diff",
      tight,
    );
    expect(two.panels?.kind).toBe("stack");
    expect(panelSurfacesOf(two)).toEqual(["view", "diff"]);
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
