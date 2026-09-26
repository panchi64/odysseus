/**
 * Which queued message the composer's arrow keys land on — the choice, without the
 * editing.
 *
 * The composer recalls the operator's queued messages the way a shell recalls its
 * history: ArrowUp from an empty field opens the **newest**, ArrowUp again walks to the
 * one before it, ArrowDown walks back and steps out of the list past the newest. The
 * order is the transcript's, which is the order the operator sent them in and the order
 * the run will deliver them — never an order derived here.
 *
 * Pure so the walk is testable on its own; `composerRecall.ts` owns the hold and the
 * draft, through the same `queuedEdit.ts` protocol the other two surfaces follow.
 */

export type RecallDirection = "older" | "newer";

/**
 * The queued message to move to, or `null` when there is none that way.
 *
 * `order` is the queued ids oldest-first; `current` is the one being edited, or `null`
 * when nothing is. A `current` that has left the list (injected, withdrawn) counts as
 * nothing being edited, so a step never resolves relative to a message that is gone.
 */
export function recallStep(
  order: readonly string[],
  current: string | null,
  direction: RecallDirection,
): string | null {
  const at = current === null ? -1 : order.indexOf(current);
  if (at === -1)
    // From outside the list only "older" enters it, and it enters at the newest.
    return direction === "older" ? (order.at(-1) ?? null) : null;
  const next = direction === "older" ? at - 1 : at + 1;
  return order[next] ?? null;
}
