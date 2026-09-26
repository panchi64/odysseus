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
 *  `configured` is what keeps this quiet when there is nothing to judge yet — and it
 *  covers two states, not one. An **empty workspace** has no window, but "your endpoint
 *  doesn't report a context window" is the wrong thing to tell someone who hasn't added
 *  an endpoint: that state has its own surfacing and this would talk over it. A
 *  workspace still **loading its bindings** has no window either, and answering before
 *  the backend has said what `main` resolves to would put a fault on screen that no one
 *  has established — the caller passes false until the roles resource is ready, so the
 *  composer opens quiet and the message only ever appears once it is actually true. */
export function sendBlocker(
  configured: boolean,
  contextWindow: number | null,
): string | null {
  if (!configured || contextWindow !== null) return null;
  return (
    "This model's endpoint doesn't report a context window, so the conversation " +
    "can't be kept inside it. Set one on the endpoint under Settings › Models › " +
    "Advanced."
  );
}

/** Where a message's attachments stand at the moment SEND is pressed.
 *
 *  - `ready` — nothing is in flight or failed; the message can go now.
 *  - `pending` — at least one file is still uploading or extracting, and none has
 *    failed. The composer holds the message and sends it the moment they settle,
 *    rather than sending without them (which silently dropped the file) or refusing
 *    (which makes the operator watch a chip and press SEND again).
 *  - `failed` — at least one file failed. Failure outranks pending: holding for the
 *    rest would only end at the same broken attachment, so the operator is told now.
 *
 *  Structural, so the design system's `ComposerAttachment` fits without this module
 *  depending on `~/ui`. */
export type AttachmentGate = "ready" | "pending" | "failed";

export function attachmentGate(
  items: readonly { status: string }[],
): AttachmentGate {
  if (items.some((a) => a.status === "error")) return "failed";
  if (items.some((a) => a.status === "uploading" || a.status === "extracting"))
    return "pending";
  return "ready";
}
