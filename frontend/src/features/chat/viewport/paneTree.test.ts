/** The layout's editing rules.
 *
 *  Exercised against synthetic surfaces rather than the registry's, which is the reason
 *  the module is parameterised over the id at all: the collapse cases below need several
 *  distinct surfaces of each shape, and the registry is not obliged to have them at any
 *  given moment.
 *
 *  The properties worth pinning are the ones a layout can quietly get wrong and still
 *  render: strips keeping registry order however they arrived, a split collapsing to its
 *  surviving child rather than to a hole, and a stack losing its active tab.
 */

import { describe, expect, test } from "bun:test";
import {
  closeSurface,
  emptyLayout,
  hasSurface,
  isEmpty,
  leaf,
  openSurface,
  panelSurfacesOf,
  surfacesOf,
  toggleSurface,
  type Layout,
  type PaneNode,
  type PaneShape,
} from "./paneTree";

/** Two strips and three panels, declared in the order they stack. */
type Id = "plan" | "agents" | "view" | "diff" | "files";

const SHAPE: Record<Id, PaneShape> = {
  plan: "strip",
  agents: "strip",
  view: "panel",
  diff: "panel",
  files: "panel",
};
const ORDER: Id[] = ["plan", "agents", "view", "diff", "files"];
const order = (id: Id): number => ORDER.indexOf(id);

const open = (layout: Layout<Id>, id: Id): Layout<Id> =>
  openSurface(layout, id, SHAPE[id], order);
const toggle = (layout: Layout<Id>, id: Id): Layout<Id> =>
  toggleSurface(layout, id, SHAPE[id], order);
const empty = (): Layout<Id> => emptyLayout<Id>();

const split = (
  a: PaneNode<Id>,
  b: PaneNode<Id>,
  dir: "row" | "col" = "col",
): PaneNode<Id> => ({ kind: "split", dir, ratio: 0.5, a, b });

describe("opening", () => {
  test("an empty layout is empty, and stops being so", () => {
    expect(isEmpty(empty())).toBe(true);
    expect(isEmpty(open(empty(), "view"))).toBe(false);
  });

  test("opening the same surface twice is the same layout", () => {
    const once = open(empty(), "view");
    expect(open(once, "view")).toBe(once);
  });

  test("a panel replaces the panel region", () => {
    const layout = open(open(empty(), "view"), "diff");
    expect(panelSurfacesOf(layout)).toEqual(["diff"]);
  });

  test("strips hold registry order however they arrived", () => {
    const late = open(open(empty(), "agents"), "plan");
    expect(late.strips).toEqual(["plan", "agents"]);
  });

  test("strips and panels occupy different regions", () => {
    const layout = open(open(empty(), "view"), "plan");
    expect(layout.strips).toEqual(["plan"]);
    expect(panelSurfacesOf(layout)).toEqual(["view"]);
    // Strips read first, matching how the panel stacks them.
    expect(surfacesOf(layout)).toEqual(["plan", "view"]);
  });
});

describe("closing", () => {
  test("closing something absent returns the very same layout", () => {
    const layout = open(empty(), "view");
    expect(closeSurface(layout, "diff")).toBe(layout);
  });

  test("closing the only panel empties the region, not the strips", () => {
    const layout = closeSurface(open(open(empty(), "view"), "plan"), "view");
    expect(layout.panels).toBeNull();
    expect(layout.strips).toEqual(["plan"]);
    expect(isEmpty(layout)).toBe(false);
  });

  test("a split collapses to its surviving child", () => {
    const layout: Layout<Id> = {
      strips: [],
      panels: split(leaf<Id>("view"), leaf<Id>("diff")),
    };
    expect(closeSurface(layout, "view").panels).toEqual(leaf<Id>("diff"));
    expect(closeSurface(layout, "diff").panels).toEqual(leaf<Id>("view"));
  });

  test("a nested split collapses only as far as it has to", () => {
    const layout: Layout<Id> = {
      strips: [],
      panels: split(
        leaf<Id>("view"),
        split(leaf<Id>("diff"), leaf<Id>("files")),
      ),
    };
    const after = closeSurface(layout, "diff");
    expect(panelSurfacesOf(after)).toEqual(["view", "files"]);
    expect(after.panels?.kind).toBe("split");
  });

  test("closing the last two surfaces of a split empties the region", () => {
    let layout: Layout<Id> = {
      strips: [],
      panels: split(leaf<Id>("view"), leaf<Id>("diff")),
    };
    layout = closeSurface(layout, "view");
    layout = closeSurface(layout, "diff");
    expect(layout.panels).toBeNull();
    expect(isEmpty(layout)).toBe(true);
  });

  test("an untouched subtree keeps its reference", () => {
    const keep = split(leaf<Id>("diff"), leaf<Id>("files"));
    const layout: Layout<Id> = {
      strips: [],
      panels: split(leaf<Id>("view"), keep),
    };
    // "view" is the one removed, so the whole right-hand subtree is handed back
    // as-is rather than rebuilt.
    expect(closeSurface(layout, "view").panels).toBe(keep);
  });
});

describe("stacks", () => {
  const stack = (surfaces: Id[], active: Id): PaneNode<Id> => ({
    kind: "stack",
    surfaces,
    active,
  });

  test("a stack of three loses one and stays a stack", () => {
    const layout: Layout<Id> = {
      strips: [],
      panels: stack(["view", "diff", "files"], "diff"),
    };
    const after = closeSurface(layout, "files").panels;
    expect(after).toEqual(stack(["view", "diff"], "diff"));
  });

  test("closing the active tab falls to the first survivor", () => {
    const layout: Layout<Id> = {
      strips: [],
      panels: stack(["view", "diff", "files"], "view"),
    };
    const after = closeSurface(layout, "view").panels;
    expect(after).toEqual(stack(["diff", "files"], "diff"));
  });

  test("a stack down to one becomes a leaf", () => {
    const layout: Layout<Id> = {
      strips: [],
      panels: stack(["view", "diff"], "view"),
    };
    expect(closeSurface(layout, "view").panels).toEqual(leaf<Id>("diff"));
  });
});

describe("toggling", () => {
  test("a surface goes in and comes back out", () => {
    const opened = toggle(empty(), "view");
    expect(hasSurface(opened, "view")).toBe(true);
    expect(isEmpty(toggle(opened, "view"))).toBe(true);
  });

  test("toggling a strip leaves the panel alone", () => {
    const layout = toggle(toggle(empty(), "view"), "plan");
    const after = toggle(layout, "plan");
    expect(after.strips).toEqual([]);
    expect(panelSurfacesOf(after)).toEqual(["view"]);
  });
});
