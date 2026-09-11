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
 * **The policy is a predicate, not a computed layout.** `fits` answers whether a shape
 * would leave every surface above its minimum, and `insertPanel` tries column, then row,
 * then a tabbed stack. Nothing here computes rectangles, because nothing needs them: flex
 * lays the panes out from this same tree at render time, and what the policy has to decide
 * before committing to a shape is only whether that shape would be legible.
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

/** A box to lay a pane out in. Pixels; only the ratios matter to the rules. */
export interface Box {
  width: number;
  height: number;
}

/** The smallest box a surface is worth showing in. */
export interface SizeLimits {
  minWidth: number;
  minHeight: number;
}

/** Height the tab strip costs a stack, so stacking is not free in the fit check. */
const STACK_TABS_HEIGHT = 36;

/**
 * Whether `node` can be laid out in `box` with every surface above its minimum.
 *
 * This is the whole of the splitting policy's judgement, and it is a *predicate*
 * rather than a computed set of rectangles because nothing needs the rectangles:
 * flex lays the panes out from the same tree at render time. What the policy needs
 * to know before it commits to a shape is only whether that shape would be legible.
 */
export function fits<Id extends string>(
  node: PaneNode<Id>,
  box: Box,
  limits: (id: Id) => SizeLimits,
): boolean {
  switch (node.kind) {
    case "leaf": {
      const { minWidth, minHeight } = limits(node.surface);
      return box.width >= minWidth && box.height >= minHeight;
    }
    case "stack": {
      // Tabs share one box, less the strip that switches them, so a stack fits
      // exactly when its most demanding member does.
      const inner = {
        width: box.width,
        height: box.height - STACK_TABS_HEIGHT,
      };
      return node.surfaces.every((s) =>
        fits<Id>({ kind: "leaf", surface: s }, inner, limits),
      );
    }
    case "split": {
      const [a, b] =
        node.dir === "col"
          ? [
              { width: box.width * node.ratio, height: box.height },
              { width: box.width * (1 - node.ratio), height: box.height },
            ]
          : [
              { width: box.width, height: box.height * node.ratio },
              { width: box.width, height: box.height * (1 - node.ratio) },
            ];
      return fits(node.a, a, limits) && fits(node.b, b, limits);
    }
  }
}

/** Every surface in `node`, flattened into one tabbed pane. */
function flatten<Id extends string>(node: PaneNode<Id>, add: Id): PaneNode<Id> {
  const surfaces = [...surfacesOfNode(node), add];
  return { kind: "stack", surfaces, active: add };
}

/**
 * Where a newly opened panel goes.
 *
 * **Split if it fits, stack if it does not.** The arriving surface takes half the
 * panel region beside what is already there — a column split when the width can
 * carry both minimums, a row split when the height can, and a tabbed stack when
 * neither can. That last case is not a failure mode to be avoided: two surfaces
 * crushed below the width at which either is readable is worse than two tabs, and a
 * layout engine that cannot say "not like this" will produce it.
 *
 * The order — column first — is because these panes are taller than they are wide.
 * Splitting the long axis is what a dwindling tiler would do and it is wrong here:
 * a 384×900 column split by height twice gives three ~300px-tall panes, and nothing
 * this panel shows is legible in one.
 *
 * `cap` bounds how many panes may share the region at all. Past it the layout stacks
 * rather than splitting, however much room there is: four panes in a side panel is a
 * layout nobody reads, it is a layout they hunt through.
 */
export function insertPanel<Id extends string>(
  node: PaneNode<Id> | null,
  id: Id,
  box: Box,
  limits: (id: Id) => SizeLimits,
  cap: number,
): PaneNode<Id> {
  if (node === null) return leaf(id);
  if (surfacesOfNode(node).length >= cap) return flatten(node, id);
  for (const dir of ["col", "row"] as const) {
    const candidate: PaneNode<Id> = {
      kind: "split",
      dir,
      ratio: 0.5,
      a: node,
      b: leaf(id),
    };
    if (fits(candidate, box, limits)) return candidate;
  }
  return flatten(node, id);
}

/**
 * Add `id` to the layout, or return it unchanged when it is already there.
 *
 * A strip is inserted so the list stays in `order` however it arrived — the order
 * strips stack in is a property of the registry, not of the sequence the operator
 * happened to click them in.
 *
 * A panel goes through `insertPanel`, which decides between splitting and stacking.
 * Callers that cannot measure a box — a migration rebuilding a layout, a test —
 * pass none, and the panel region simply takes the new surface on its own.
 */
export function openSurface<Id extends string>(
  layout: Layout<Id>,
  id: Id,
  shape: PaneShape,
  order: (id: Id) => number,
  tiling?: { box: Box; limits: (id: Id) => SizeLimits; cap: number },
): Layout<Id> {
  if (hasSurface(layout, id)) return layout;
  if (shape === "strip") {
    const strips = [...layout.strips, id].sort((x, y) => order(x) - order(y));
    return { ...layout, strips };
  }
  if (!tiling) return { ...layout, panels: leaf(id) };
  return {
    ...layout,
    panels: insertPanel(
      layout.panels,
      id,
      tiling.box,
      tiling.limits,
      tiling.cap,
    ),
  };
}

/** Bring `id` to the front of whichever stack holds it. A no-op elsewhere. */
export function focusInStack<Id extends string>(
  layout: Layout<Id>,
  id: Id,
): Layout<Id> {
  if (layout.panels === null) return layout;
  const walk = (node: PaneNode<Id>): PaneNode<Id> => {
    switch (node.kind) {
      case "leaf":
        return node;
      case "stack":
        return node.surfaces.includes(id) && node.active !== id
          ? { ...node, active: id }
          : node;
      case "split": {
        const a = walk(node.a);
        const b = walk(node.b);
        return a === node.a && b === node.b ? node : { ...node, a, b };
      }
    }
  };
  const panels = walk(layout.panels);
  return panels === layout.panels ? layout : { ...layout, panels };
}

/** Change a split's proportion, addressed by the path of `a`/`b` steps to it. */
export function resizeSplit<Id extends string>(
  layout: Layout<Id>,
  path: readonly ("a" | "b")[],
  ratio: number,
): Layout<Id> {
  if (layout.panels === null) return layout;
  const clamped = Math.min(0.85, Math.max(0.15, ratio));
  const walk = (node: PaneNode<Id>, at: number): PaneNode<Id> => {
    if (node.kind !== "split") return node;
    if (at === path.length) return { ...node, ratio: clamped };
    const step = path[at];
    const child = walk(node[step], at + 1);
    return child === node[step] ? node : { ...node, [step]: child };
  };
  const panels = walk(layout.panels, 0);
  return panels === layout.panels ? layout : { ...layout, panels };
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
