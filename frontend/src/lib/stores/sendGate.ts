/** Whether a chat turn can be sent, and why not.
 *
 *  Its own module rather than a function inside `models.ts` because it is policy, not
 *  state: it reads nothing, subscribes to nothing, and is the kind of decision worth
 *  checking directly. (`models.ts` builds its resources at module scope, so importing
 *  it outside a reactive root fails — which is a good reason to keep a pure rule out
 *  of it, and a poor one to leave the rule untested.)
 */

/** Why a chat turn can't be sent right now, or null when it can.
 *
 *  The frontend half of the backend's send gate: without a context window every
 *  mechanism that keeps a thread inside its limit is inert, so the backend refuses the
 *  turn (422) rather than run it unguarded. Mirrored here so the refusal arrives
 *  *before* the operator commits a message to it — a SEND that accepts the text and
 *  then rejects it is a worse version of the same stop.
 *
 *  `configured` is what keeps this quiet on an empty workspace. Nothing configured has
 *  no window either, but "your endpoint doesn't report a context window" is the wrong
 *  thing to tell someone who hasn't added an endpoint yet: that state has its own
 *  surfacing, and this would talk over it. */
export function sendBlocker(
  configured: boolean,
  contextWindow: number | null,
): string | null {
  if (!configured || contextWindow !== null) return null;
  return (
    "This model's endpoint doesn't report a context window, so the conversation " +
    "can't be kept inside it. Set one on the endpoint under Settings › Models."
  );
}
