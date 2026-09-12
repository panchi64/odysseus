/**
 * What the viewport can show, as data.
 *
 * The panel held exactly one thing for as long as there was exactly one thing to hold, so
 * "which panel is in the slot" was a `Show` in the mount and a string union beside the
 * width keys. Adding a second content type that way costs a branch, a width rule and a
 * toggle every time. This file is the other half of that trade: **what exists** lives
 * here, and the components that render it derive everything else — the same discipline
 * `app/settings-dialog/sections.ts` and `app/nav/areas.ts` already keep.
 *
 * **Surfaces are not interchangeable rectangles, and the shape says so.** A file tree and
 * a diff want height *and* width and are read at length; a plan is five short rows. A
 * layout that treats those the same gives the plan half the panel, which is why the shape
 * is declared rather than inferred from content: it is a fact about the surface, known
 * before it has anything in it.
 *
 * Every id here must have a renderer, and because `SurfaceId` is derived from this array
 * rather than declared beside it, a missing one is a compile error rather than a blank
 * pane. So a surface is added here **in the same change** that adds its renderer, never
 * ahead of it — a row with nothing behind it is a button that opens onto nothing.
 */

import type { IconName } from "~/ui";

/** How a surface wants to be laid out. See the module note — this drives where the
 *  host puts it, not merely how it looks. */
export type SurfaceShape = "strip" | "panel";

interface SurfaceBase {
  id: string;
  /** The header button's tooltip and the surface frame's label. */
  label: string;
  icon: IconName;
}

/** A few short rows, stacked above the panels at their natural height. */
export interface StripSpec extends SurfaceBase {
  shape: "strip";
  /** Rows shown before the strip stops growing and scrolls inside itself. A strip
   *  that can push the panels off the bottom is a panel wearing a strip's clothes. */
  maxRows: number;
}

/** A region read at length, tiled in whatever the strips leave. */
export interface PanelSpec extends SurfaceBase {
  shape: "panel";
  /** Below this the surface is not worth showing — the host stacks or tabs instead
   *  of splitting. */
  minWidth: number;
  minHeight: number;
  /** What the panel widens to when this surface arrives into a narrower one. */
  defaultWidth: number;
}

export type SurfaceSpec = StripSpec | PanelSpec;

/**
 * Every surface, in the order the header offers them.
 *
 * Ordering is deliberate rather than alphabetical, and it is also the order strips
 * stack in — so it reads top-to-bottom the way the panel does.
 */
export const SURFACES = [
  {
    id: "tasks",
    shape: "strip",
    label: "Tasks",
    icon: "note",
    // Eight rows before it stops growing. A list longer than that is one the operator
    // scrolls, not one that pushes the panels off the bottom.
    maxRows: 8,
  },
  {
    // A **panel**, where the task list above is a strip, because the two are different
    // kinds of thing: that one is a handful of short lines glanced at while work runs,
    // this is a document read end-to-end before answering. A plan the operator has to
    // scroll eight rows at a time is a plan they approve without reading.
    id: "plan",
    shape: "panel",
    label: "Plan",
    icon: "note",
    minWidth: 380,
    minHeight: 280,
    defaultWidth: 520,
  },
  {
    id: "agents",
    shape: "strip",
    label: "Agents",
    icon: "users",
    // Six rows of delegations. Past that the agent is farming out more work than
    // the operator can follow at a glance, and the list scrolls.
    maxRows: 6,
  },
  {
    id: "diff",
    shape: "panel",
    label: "Changes",
    icon: "compare",
    // A split diff needs real width before either column is readable; below this
    // it renders stacked, which is why the floor is higher than the View's.
    minWidth: 420,
    minHeight: 260,
    defaultWidth: 560,
  },
  {
    id: "view",
    shape: "panel",
    label: "View",
    icon: "eye",
    // The width numbers the panel already used, now attached to the surface that
    // wanted them rather than to the panel that happened to hold it.
    minWidth: 320,
    minHeight: 240,
    defaultWidth: 384,
  },
  {
    id: "files",
    shape: "panel",
    label: "Files",
    icon: "file",
    minWidth: 320,
    minHeight: 240,
    defaultWidth: 420,
  },
] as const satisfies readonly SurfaceSpec[];

export type SurfaceId = (typeof SURFACES)[number]["id"];

/** Every id, in registry order. */
export const SURFACE_IDS: readonly SurfaceId[] = SURFACES.map((s) => s.id);

/** The one cast in this module, and it is sound by construction: `SurfaceId` is
 *  derived from the very array being indexed, so every key is present. */
export const SURFACE_BY_ID = Object.fromEntries(
  SURFACES.map((s) => [s.id, s]),
) as Record<SurfaceId, SurfaceSpec>;

export function surfaceSpec(id: SurfaceId): SurfaceSpec {
  return SURFACE_BY_ID[id];
}

/** Narrowing helpers — the shape is a discriminant, and the layout asks constantly. */
export const isPanelSpec = (spec: SurfaceSpec): spec is PanelSpec =>
  spec.shape === "panel";
export const isStripSpec = (spec: SurfaceSpec): spec is StripSpec =>
  spec.shape === "strip";

/** Where `id` belongs in the layout. */
export const shapeOf = (id: SurfaceId): SurfaceShape => SURFACE_BY_ID[id].shape;

/** Registry position, for keeping strips in declaration order however they arrive. */
export const orderOf = (id: SurfaceId): number => SURFACE_IDS.indexOf(id);
