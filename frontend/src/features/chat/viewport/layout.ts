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
import { orderOf, shapeOf, SURFACE_BY_ID, type SurfaceId } from "./surfaces";

/** The layout, over the surfaces that actually exist. */
export type ViewportLayout = tree.Layout<SurfaceId>;
export type ViewportPane = tree.PaneNode<SurfaceId>;

export const emptyLayout = (): ViewportLayout => tree.emptyLayout<SurfaceId>();
export const leaf = (surface: SurfaceId): ViewportPane => tree.leaf(surface);

export const openSurface = (
  layout: ViewportLayout,
  id: SurfaceId,
): ViewportLayout => tree.openSurface(layout, id, shapeOf(id), orderOf);

export const toggleSurface = (
  layout: ViewportLayout,
  id: SurfaceId,
): ViewportLayout => tree.toggleSurface(layout, id, shapeOf(id), orderOf);

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
 * Drop surfaces a persisted layout names that the registry no longer has.
 *
 * A layout outlives the code that wrote it — it lives in localStorage, and a surface
 * can be renamed or removed between one session and the next. Reading one back has to
 * be total: an unknown id is dropped rather than rendered as a pane with no renderer,
 * which is the one failure a build cannot see.
 */
export function pruneLayout(layout: ViewportLayout): ViewportLayout {
  let next = layout;
  for (const id of tree.surfacesOf(layout)) {
    if (!isSurfaceId(id)) next = tree.closeSurface(next, id);
  }
  return next;
}
