/**
 * Whether each surface has anything to show.
 *
 * One module, because the alternative is a `switch` on the surface id wherever the question
 * is asked — the header bar asks it to decide which buttons exist, and the panel asks it to
 * decide whether it is worth being open at all. Two dispatches drift; one does not.
 *
 * **A source reads signals the room already has.** It is handed the accessors rather than
 * reaching for a store, and it may not open a fetch of its own: a surface nobody has opened
 * still has its availability evaluated on every render, so a source that polled would make
 * a closed panel cost network. Where a surface's data genuinely needs fetching — the
 * worktree diff — the fetch belongs to whoever already owns it and arrives here as an
 * accessor like the rest.
 *
 * Keyed by `SurfaceId`, so a surface added to the registry without a source is a compile
 * error rather than a button that never appears.
 */

import type { PlanItem } from "~/lib/stream/events";
import type { BranchState } from "../data";
import type { SurfaceId } from "./surfaces";
import type { ViewItem } from "./viewItems";

export interface SurfaceSource {
  /** Whether the surface has content. A surface that does not is offered nowhere:
   *  no header button, and no place in a restored layout. */
  available: () => boolean;
}

/** What the sources read. Accessors, never stores — see the module note. */
export interface SurfaceDeps {
  viewItems: () => ViewItem[];
  plan: () => PlanItem[];
  branch: () => BranchState | null | undefined;
}

export function createSurfaceSources(
  deps: SurfaceDeps,
): Record<SurfaceId, SurfaceSource> {
  return {
    // A thread's View is its captured versions plus any live head.
    view: { available: () => deps.viewItems().length > 0 },
    // An empty task list is not a plan. The agent writes one the moment it has
    // something to write, so "no rows" and "no plan" are the same state.
    plan: { available: () => deps.plan().length > 0 },
    // Only a code thread has a branch at all; the fetch answers 404 for every other
    // kind, which is the ordinary case rather than a failure.
    diff: { available: () => Boolean(deps.branch()) },
    // The workspace is browsable once a version of it has been captured — the same
    // snapshots the View lists, read as a tree rather than as versions.
    files: {
      available: () => deps.viewItems().some((i) => i.snapshot),
    },
  };
}
