/**
 * What the viewport is showing, and where — as a value, not as component state.
 *
 * The layout is persisted per conversation and restored on return, so it has to be a
 * plain serialisable structure the host renders rather than something assembled during
 * render. Everything here is pure: no signals, no DOM, no clock. That is what makes the
 * tiling rules testable at all, and the rules are the part most likely to be wrong.
 *
 * **Two regions, because surfaces come in two shapes** (see `surfaces.ts`). Strips stack
 * above at their natural height in registry order; panels tile in what is left. Keeping
 * them apart is what stops a five-row plan from being handed half the panel by a layout
 * engine that cannot tell it apart from a diff.
 *
 * **The tree is general; the editing operations deliberately are not.** A `split` nests
 * arbitrarily and a `stack` holds any number, because that is what falls out of repeated
 * splitting and of the tabbed fallback. But the only ways to *change* a layout are open,
 * close and resize — no drag-to-rearrange, no arbitrary surgery — so the reachable shapes
 * stay a small, predictable subset of what the type admits.
 *
 * **Nothing here imports the registry.** The module is about geometry, and it is
 * parameterised over the surface id so it can be exercised against synthetic surfaces
 * rather than only against whichever ones happen to exist today. `openSurface` is the one
 * operation that needs to know a surface's shape, and it is told rather than looking it
 * up.
 *
 * At this stage opening a panel **replaces** whatever panel was there, which is what the
 * panel did before any of this existed. The splitting policy arrives with tiling; the
 * structure is here now so the persisted format does not have to change again to get it.
 */

/** How a surface wants to be laid out. Mirrors `surfaces.ts`'s `SurfaceShape`, declared
 *  here too so this module owes the registry nothing. */
export type PaneShape = "strip" | "panel";

/** One node of the panel region.
 *
 *  `stack` is a tabbed pane, and it is not optional: it is what a split degrades to
 *  when neither child can meet its minimum, and without it the answer to "this does
 *  not fit" would be a broken layout instead of a tab strip. */
export type PaneNode<Id extends string = string> =
  | { kind: "leaf"; surface: Id }
  | { kind: "stack"; surfaces: Id[]; active: Id }
  | {
      kind: "split";
      /** `row` stacks `a` above `b`; `col` puts them side by side. */
      dir: "row" | "col";
      /** `a`'s share of the axis, 0..1. */
      ratio: number;
      a: PaneNode<Id>;
      b: PaneNode<Id>;
    };

export interface Layout<Id extends string = string> {
  /** Registry order, always — see `openSurface`. */
  strips: Id[];
  panels: PaneNode<Id> | null;
}

/** Nothing open. Distinct from "the panel is closed", which is the absence of a
 *  layout altogether — see `persistence.ts`. */
export function emptyLayout<Id extends string>(): Layout<Id> {
  return { strips: [], panels: null };
}

export const leaf = <Id extends string>(surface: Id): PaneNode<Id> => ({
  kind: "leaf",
  surface,
});

/** Every surface in `node`, left to right / top to bottom. */
export function surfacesOfNode<Id extends string>(node: PaneNode<Id>): Id[] {
  switch (node.kind) {
    case "leaf":
      return [node.surface];
    case "stack":
      return [...node.surfaces];
    case "split":
      return [...surfacesOfNode(node.a), ...surfacesOfNode(node.b)];
  }
}

/** Every surface on screen — strips first, matching the visual order. */
export function surfacesOf<Id extends string>(layout: Layout<Id>): Id[] {
  return [
    ...layout.strips,
    ...(layout.panels ? surfacesOfNode(layout.panels) : []),
  ];
}

/** Just the panel-shaped surfaces — what the width floor is computed over. */
export function panelSurfacesOf<Id extends string>(layout: Layout<Id>): Id[] {
  return layout.panels ? surfacesOfNode(layout.panels) : [];
}

export function hasSurface<Id extends string>(
  layout: Layout<Id>,
  id: Id,
): boolean {
  return surfacesOf(layout).includes(id);
}

export function isEmpty<Id extends string>(layout: Layout<Id>): boolean {
  return layout.strips.length === 0 && layout.panels === null;
}

/**
 * Add `id` to the layout, or return it unchanged when it is already there.
 *
 * A strip is inserted so the list stays in `order` however it arrived — the order
 * strips stack in is a property of the registry, not of the sequence the operator
 * happened to click them in.
 *
 * A panel replaces the panel region. That is this stage's whole policy, and it
 * reproduces the behavior the single-occupant panel already had.
 */
export function openSurface<Id extends string>(
  layout: Layout<Id>,
  id: Id,
  shape: PaneShape,
  order: (id: Id) => number,
): Layout<Id> {
  if (hasSurface(layout, id)) return layout;
  if (shape === "strip") {
    const strips = [...layout.strips, id].sort((x, y) => order(x) - order(y));
    return { ...layout, strips };
  }
  return { ...layout, panels: leaf(id) };
}

/** Drop `id` from `node`, collapsing whatever it leaves behind: a split whose child
 *  empties becomes its surviving child, and a stack down to one becomes a leaf. */
function closeInNode<Id extends string>(
  node: PaneNode<Id>,
  id: Id,
): PaneNode<Id> | null {
  switch (node.kind) {
    case "leaf":
      return node.surface === id ? null : node;
    case "stack": {
      const surfaces = node.surfaces.filter((s) => s !== id);
      if (surfaces.length === node.surfaces.length) return node;
      if (surfaces.length === 0) return null;
      if (surfaces.length === 1) return leaf(surfaces[0]);
      return {
        kind: "stack",
        surfaces,
        // A stack whose active tab just closed falls to the first remaining one
        // rather than to nothing.
        active: surfaces.includes(node.active) ? node.active : surfaces[0],
      };
    }
    case "split": {
      const a = closeInNode(node.a, id);
      const b = closeInNode(node.b, id);
      if (a === null) return b;
      if (b === null) return a;
      // Identity when neither side changed, so an unaffected subtree keeps its
      // reference and a consumer diffing on it sees no churn.
      return a === node.a && b === node.b ? node : { ...node, a, b };
    }
  }
}

/** Remove `id` wherever it is. Unchanged (by reference) when it was not there.
 *
 *  No shape argument, unlike `openSurface`: a surface is in the strips or in the
 *  tree, never both, so removing it from each is unambiguous without asking which
 *  it should have been in. That also makes close correct for a layout persisted
 *  before a surface's shape was changed. */
export function closeSurface<Id extends string>(
  layout: Layout<Id>,
  id: Id,
): Layout<Id> {
  if (!hasSurface(layout, id)) return layout;
  return {
    strips: layout.strips.filter((s) => s !== id),
    panels: layout.panels ? closeInNode(layout.panels, id) : null,
  };
}

/** Open `id` if it is closed, close it if it is open — what a header button does. */
export function toggleSurface<Id extends string>(
  layout: Layout<Id>,
  id: Id,
  shape: PaneShape,
  order: (id: Id) => number,
): Layout<Id> {
  return hasSurface(layout, id)
    ? closeSurface(layout, id)
    : openSurface(layout, id, shape, order);
}
