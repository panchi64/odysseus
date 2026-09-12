/** The layout over the *real* registry.
 *
 *  `paneTree.test.ts` proves the geometry against synthetic surfaces, which is the right
 *  place for the rules. This proves the wiring: that the surfaces the app actually ships
 *  are declared with the shapes the layout then files them under. A task list declared as
 *  a panel by mistake is a five-row list handed half the viewport, and nothing in the pure
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

  test("a task list is a strip; a plan and a view are panels", () => {
    expect(shapeOf("tasks")).toBe("strip");
    expect(shapeOf("view")).toBe("panel");
    // The one that changed. A plan is read end to end before it is answered, so it
    // gets a panel's width where the checklist gets a strip's height.
    expect(shapeOf("plan")).toBe("panel");
  });
});

describe("filing a surface by its shape", () => {
  test("a strip lands in the strips, not the panel region", () => {
    const layout = openSurface(emptyLayout(), "tasks");
    expect(layout.strips).toEqual(["tasks"]);
    expect(panelSurfacesOf(layout)).toEqual([]);
  });

  test("a panel lands in the panel region", () => {
    const layout = openSurface(emptyLayout(), "view");
    expect(layout.strips).toEqual([]);
    expect(panelSurfacesOf(layout)).toEqual(["view"]);
  });

  test("the two coexist, strips first", () => {
    let layout = toggleSurface(emptyLayout(), "view");
    layout = toggleSurface(layout, "tasks");
    expect(surfacesOf(layout)).toEqual(["tasks", "view"]);
  });

  test("closing one leaves the other", () => {
    let layout = openSurface(openSurface(emptyLayout(), "tasks"), "view");
    layout = closeSurface(layout, "view");
    expect(hasSurface(layout, "tasks")).toBe(true);
    expect(isEmpty(layout)).toBe(false);
    layout = closeSurface(layout, "tasks");
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

  test("a surface filed under a shape it no longer has is dropped too", () => {
    // Every layout written before the split names `plan` in the strips, because that
    // is what it was. Rendering a document in one row of an eight-row strip is not a
    // crash — it just looks broken — which is exactly why it has to be caught here.
    const stale = {
      strips: ["plan" as const],
      panels: { kind: "leaf" as const, surface: "view" as const },
    };
    const pruned = pruneLayout(stale);
    expect(pruned.strips).toEqual([]);
    expect(panelSurfacesOf(pruned)).toEqual(["view"]);
  });

  test("a surface filed correctly is left alone", () => {
    const sound = {
      strips: ["tasks" as const],
      panels: { kind: "leaf" as const, surface: "plan" as const },
    };
    const pruned = pruneLayout(sound);
    expect(pruned.strips).toEqual(["tasks"]);
    expect(panelSurfacesOf(pruned)).toEqual(["plan"]);
  });
});
