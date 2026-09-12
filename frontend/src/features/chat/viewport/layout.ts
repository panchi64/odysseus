/**
 * The layout, bound to the registry.
 *
 * `paneTree.ts` is deliberately ignorant of which surfaces exist — it is geometry, and
 * being parameterised over the id is what lets its rules be tested against surfaces the
 * registry need not currently have. That leaves `openSurface` needing to be *told* a
 * surface's shape and sort position on every call, which is right for the geometry module
 * and tedious everywhere else.
 *
 * This is the one place the two meet: the operations the host actually calls, already
 * carrying the registry's answers. Nothing else should be passing `shapeOf` around.
 */

import * as tree from "./paneTree";
import {
  isPanelSpec,
  orderOf,
  shapeOf,
  surfaceSpec,
  SURFACE_BY_ID,
  type SurfaceId,
} from "./surfaces";

/** The layout, over the surfaces that actually exist. */
export type ViewportLayout = tree.Layout<SurfaceId>;
export type ViewportPane = tree.PaneNode<SurfaceId>;

export const emptyLayout = (): ViewportLayout => tree.emptyLayout<SurfaceId>();
export const leaf = (surface: SurfaceId): ViewportPane => tree.leaf(surface);

/** Each surface's smallest legible box, from the registry. Strips are not tiled, so
 *  they impose nothing — the panel region is the only thing being fitted. */
const limits = (id: SurfaceId): tree.SizeLimits => {
  const spec = surfaceSpec(id);
  return isPanelSpec(spec)
    ? { minWidth: spec.minWidth, minHeight: spec.minHeight }
    : { minWidth: 0, minHeight: 0 };
};

/** How the panel region should be divided when a surface arrives: the box there is
 *  to divide, and how many panes may share it. Omitted where nothing has measured a
 *  box yet, in which case the arriving surface simply takes the region. */
export interface TilingContext {
  box: tree.Box;
  cap: number;
}

const withLimits = (
  tiling: TilingContext | undefined,
): { box: tree.Box; limits: typeof limits; cap: number } | undefined =>
  tiling ? { box: tiling.box, limits, cap: tiling.cap } : undefined;

export const openSurface = (
  layout: ViewportLayout,
  id: SurfaceId,
  tiling?: TilingContext,
): ViewportLayout =>
  tree.openSurface(layout, id, shapeOf(id), orderOf, withLimits(tiling));

export const toggleSurface = (
  layout: ViewportLayout,
  id: SurfaceId,
  tiling?: TilingContext,
): ViewportLayout =>
  hasSurface(layout, id)
    ? tree.closeSurface(layout, id)
    : openSurface(layout, id, tiling);

export const focusInStack = (
  layout: ViewportLayout,
  id: SurfaceId,
): ViewportLayout => tree.focusInStack(layout, id);

export const resizeSplit = (
  layout: ViewportLayout,
  path: readonly ("a" | "b")[],
  ratio: number,
): ViewportLayout => tree.resizeSplit(layout, path, ratio);

export const closeSurface = (
  layout: ViewportLayout,
  id: SurfaceId,
): ViewportLayout => tree.closeSurface(layout, id);

export const surfacesOf = (layout: ViewportLayout): SurfaceId[] =>
  tree.surfacesOf(layout);
export const panelSurfacesOf = (layout: ViewportLayout): SurfaceId[] =>
  tree.panelSurfacesOf(layout);
export const hasSurface = (layout: ViewportLayout, id: SurfaceId): boolean =>
  tree.hasSurface(layout, id);
export const isEmpty = (layout: ViewportLayout): boolean =>
  tree.isEmpty(layout);

/** Whether the registry still has a surface by this id. Narrows, so a persisted
 *  string can be treated as an id once it has passed. */
export const isSurfaceId = (id: string): id is SurfaceId =>
  Object.prototype.hasOwnProperty.call(SURFACE_BY_ID, id);

/**
 * Drop surfaces a persisted layout names that the registry no longer files the same way.
 *
 * A layout outlives the code that wrote it — it lives in localStorage, and a surface can
 * be renamed, removed, or **reshaped** between one session and the next. Reading one back
 * has to be total: an unknown id is dropped rather than rendered as a pane with no
 * renderer, which is the one failure a build cannot see.
 *
 * The shape check is the second half of that, and it is not hypothetical: `plan` was a
 * strip and is now a panel, so every layout written before that names it in the strip
 * list. Rendering a document in a row of an eight-row strip is not a crash, which is
 * exactly why it needs catching here — it would simply look broken. Dropped rather than
 * moved, because a surface the operator had open is one they can reopen, and guessing
 * where in the panel region it should land is a worse answer than the header button.
 */
export function pruneLayout(layout: ViewportLayout): ViewportLayout {
  let next = layout;
  for (const id of tree.surfacesOf(layout)) {
    if (!isSurfaceId(id)) {
      next = tree.closeSurface(next, id);
      continue;
    }
    const filedAsStrip = layout.strips.includes(id);
    if (filedAsStrip !== (shapeOf(id) === "strip"))
      next = tree.closeSurface(next, id);
  }
  return next;
}
