/**
 * What each surface has, and what it should do about getting it.
 *
 * One module, because the alternative is a `switch` on the surface id wherever the
 * question is asked — the header bar asks availability to decide which buttons exist, the
 * panel asks it to decide whether it is worth being open, and the arrival effect asks
 * whether a surface has earned the right to put itself on screen. Three dispatches drift;
 * one does not.
 *
 * **A source reads signals the room already has.** It is handed accessors rather than
 * reaching for a store, and it may not open a fetch of its own: a surface nobody has
 * opened still has its availability evaluated on every render, so a source that polled
 * would make a closed panel cost network. Where a surface's data genuinely needs fetching
 * — the worktree diff — the fetch belongs to whoever already owns it and arrives here as
 * an accessor like the rest.
 *
 * Keyed by `SurfaceId`, so a surface added to the registry without a source is a compile
 * error rather than a button that never appears.
 */

import type { PermissionLevel } from "../model";
import type { PlanItem } from "~/lib/stream/events";
import type { BranchState } from "../data";
import type { SurfaceId } from "./surfaces";
import type { ViewItem } from "./viewItems";

/**
 * What a surface does the first time it has something.
 *
 * - `steal` — put itself on screen. For the case where *not* seeing it leaves the
 *   operator waiting on something they do not know is waiting on them.
 * - `announce` — light its header button and otherwise stay out of the way.
 * - `silent` — appear in the header, and nothing more until asked.
 *
 * It is a **predicate, not a field on the registry**, because at least one surface's
 * answer depends on the moment rather than on what kind of surface it is: a plan that
 * needs approving is an interruption, and the same plan ticking along is not.
 */
export type Arrival = "steal" | "announce" | "silent";

export interface SurfaceSource {
  /** Whether the surface has content. A surface that does not is offered nowhere:
   *  no header button, and no place in a restored layout. */
  available: () => boolean;
  arrival: () => Arrival;
  /** What makes *this* arrival distinct from the last. A steal is claimed once per
   *  key per conversation, so a surface cannot reopen itself after a manual close —
   *  while a genuinely new arrival gets a new key and a fresh claim. A constant key
   *  means "once per thread, ever". */
  claimKey: () => string;
}

/** What the sources read. Accessors, never stores — see the module note. */
export interface SurfaceDeps {
  viewItems: () => ViewItem[];
  plan: () => PlanItem[];
  branch: () => BranchState | null | undefined;
  /** The thread's current level. `plan` is the one that cannot act. */
  permission: () => PermissionLevel;
}

export function createSurfaceSources(
  deps: SurfaceDeps,
): Record<SurfaceId, SurfaceSource> {
  return {
    // An empty task list is not a plan. The agent writes one the moment it has
    // something to write, so "no rows" and "no plan" are the same state.
    plan: {
      available: () => deps.plan().length > 0,
      // **A plan interrupts only when it is waiting on a yes.** A thread at `plan`
      // level has been offered no tool that changes anything, so the only way its
      // turn can end is by writing down what it *would* do — and then it is blocked
      // on the operator, who does not know it. That is the one state worth putting
      // on screen uninvited. A plan that merely changed while the thread can already
      // act is progress, and progress badges.
      arrival: () =>
        deps.permission() === "plan" && deps.plan().length > 0
          ? "steal"
          : "announce",
      // Keyed by the list's length, so a *revised* plan awaiting approval is a new
      // arrival and earns a fresh claim, while the same plan re-rendering does not.
      claimKey: () => `await:${deps.plan().length}`,
    },
    // Only a code thread has a branch at all; the fetch answers 404 for every other
    // kind, which is the ordinary case rather than a failure.
    diff: {
      available: () => Boolean(deps.branch()),
      // Changes accumulate for the whole length of a code thread. A panel that opened
      // itself every time the agent touched a file is a panel the operator learns to
      // close reflexively.
      arrival: () => "announce",
      claimKey: () => "",
    },
    // The workspace is browsable once a version of it has been captured — the same
    // snapshots the View lists, read as a tree rather than as versions.
    files: {
      available: () => deps.viewItems().some((i) => i.snapshot),
      // Nobody is ever waiting on a file listing.
      arrival: () => "silent",
      claimKey: () => "",
    },
    // A thread's View is its captured versions plus any live head.
    view: {
      available: () => deps.viewItems().length > 0,
      // The first artifact a thread produces is usually the thing it was asked for,
      // and a panel that stayed shut over it would be hiding the answer. Once per
      // thread, which is what the constant key buys: a later close means "not this".
      arrival: () => "steal",
      claimKey: () => "",
    },
  };
}
