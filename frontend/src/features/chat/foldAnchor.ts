import { createSignal } from "solid-js";

/** A one-shot request to take the operator to a turn they would otherwise never find.
 *
 *  A fold settles somewhere other than where it was watched. The live turn sits at the
 *  tail, where the thread is; the checkpoint it becomes belongs at the **fold boundary**,
 *  which on a long thread is far up the scroll — so the moment the summary lands, the one
 *  thing the operator was waiting for leaves the screen. What is left behind is a stretch
 *  of dimmed turns they cannot see, which is indistinguishable from nothing having
 *  happened. That is the whole bug this surface exists to fix, and it would survive the
 *  redesign without this.
 *
 *  Module-level rather than a store field for the same reason the viewport's own anchor
 *  is: it is a one-shot *request*, not state anything renders from, and a second reader
 *  would have to decide when to clear it.
 */
const [anchor, setAnchor] = createSignal<string | null>(null);

/** Ask the transcript to bring ``messageId`` into view. Idempotent — a replayed frame
 *  re-requesting the same turn is a request to look at it again, which is harmless. */
export function requestFoldAnchor(messageId: string): void {
  setAnchor(messageId);
}

/** Take the pending request, if any, clearing it. Called by the transcript, which is the
 *  only thing that can act on it: nothing below the scroll container knows where a turn
 *  is on screen. */
export function consumeFoldAnchor(): string | null {
  const id = anchor();
  if (id !== null) setAnchor(null);
  return id;
}

/** The pending request without taking it — the reactive read an effect subscribes to. */
export function pendingFoldAnchor(): string | null {
  return anchor();
}
