/**
 * Which permission level the composer holds for the thread on screen.
 *
 * The level is the one binding fact that both *moves* and is *sent* — the control changes
 * it mid-thread, and every send carries it, which is how the backend comes to persist it
 * against the conversation. That combination is what makes a stale reading dangerous
 * rather than merely wrong: a level left pointing at the thread the operator just left
 * does not sit there looking odd, it rides the next send and is written onto the thread
 * they just opened.
 *
 * So the level is held with the id of the thread it was *chosen for*, and this decides
 * what to do when the two disagree. Pure — no Solid, no resource — because the rule is
 * about which of three facts wins, and that is worth being able to state without a
 * conversation to load.
 */

import {
  DEFAULT_PERMISSION_LEVEL,
  STRICTEST_PERMISSION_LEVEL,
  type PermissionLevel,
} from "./model";

export interface PermissionSeat {
  /** The thread the level was chosen for; `null` while the thread is still unsaved. */
  owner: string | null;
  level: PermissionLevel;
  /** Whether this level is a **stand-in** for one still in flight, rather than an answer.
   *  True only in case 2 below for an existing thread: the level seated is the strictest
   *  one because the thread's own is unknown, not because anything said so. The composer
   *  reads it to render the control as pending instead of asserting a level the thread was
   *  never at — a control that flashed PLAN on every thread open would be stating a fact
   *  about the thread, and the operator would have no way to tell that flash from a thread
   *  genuinely stored at Plan. */
  provisional: boolean;
}

export interface PermissionSeatInput {
  /** The thread on screen. */
  currentId: string | null;
  /** The thread the level in hand belongs to. */
  owner: string | null;
  /** What that thread's loaded history says its level is — `undefined` while the load
   *  is still in flight, which is the case this whole rule exists for. */
  stored: PermissionLevel | undefined;
}

/**
 * Re-seat the level, or `null` for "leave it exactly where it is".
 *
 * Three answers, in the order they win:
 *
 * 1. **The thread said so.** Once its history is loaded, the stored level is the thread's
 *    own answer and nothing beats it.
 * 2. **A different thread is open and has not answered yet.** The level in hand is
 *    another conversation's, so it is dropped — and *which* level replaces it depends on
 *    whether there is a stored one still coming. An **existing** thread has a level of
 *    its own in flight, so the seat goes to the strictest one until it lands; a **new**
 *    thread (`currentId === null`) has none coming and starts at the default like any
 *    fresh thread does. This is the window the repro lives in: click a stored-plan thread
 *    while sitting at auto, send before the fetch lands, and the send would otherwise
 *    post auto with the new thread's id — which the backend persists, turning a read-only
 *    thread into an auto-approving one with nothing on screen having said so. Seating the
 *    *default* there would not close it, because the default is now Auto and Auto is the
 *    widest level there is; the only reading of an unknown level that cannot widen a
 *    thread is the narrowest one, and it errs toward asking rather than acting. That
 *    reading is flagged `provisional`, because it is a placeholder rather than a fact
 *    about the thread and must not be rendered as one.
 * 3. **Nothing to do.** The level in hand already belongs to the thread on screen — a
 *    mid-thread choice the operator made, or a staged thread's own staging.
 *
 * A staged thread adopting its backend id is *not* case 2 and must not reset: it is the
 * same thread, and the level it was created with is the one the operator picked for it.
 * That transfer is the caller's (`adopt` below), because only the caller knows a new id
 * arrived from the run that created it rather than from the rail.
 */
export function seatPermission(
  input: PermissionSeatInput,
): PermissionSeat | null {
  if (input.stored !== undefined)
    return {
      owner: input.currentId,
      level: input.stored,
      provisional: false,
    };
  if (input.owner !== input.currentId)
    return {
      owner: input.currentId,
      level:
        input.currentId === null
          ? DEFAULT_PERMISSION_LEVEL
          : STRICTEST_PERMISSION_LEVEL,
      // A staged thread's default is the answer — there is no stored level coming for it.
      // An existing thread's strictest is a placeholder for one that has not landed.
      provisional: input.currentId !== null,
    };
  return null;
}
