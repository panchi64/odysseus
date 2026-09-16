/**
 * What the operator is in the middle of typing into a queued message's editor.
 *
 * A module-level map rather than the editing bubble's own signal, and it is there for one
 * case: a run that ends while a queued message is open for editing. The teardown hands
 * undelivered text back to the composer, and it read the bubble's *saved* content — so
 * the operator got back the version they were in the middle of replacing, and the edit
 * they were protecting with a hold was the one thing lost. Two readers, one value.
 *
 * Keyed by the backend's queued-message id, so it survives the bubble being re-rendered,
 * re-ordered or rebuilt from a replay. It is deliberately not persisted: a draft is worth
 * carrying across a re-render, not across a reload, and the run it belongs to does not
 * survive one either.
 *
 * Follows the module-level seams `viewerPersistence.ts` already keeps (`viewerDirty`,
 * `activeDownload`) — a value two unrelated layers both need, owned by neither.
 */

const drafts = new Map<string, string>();

/** What is being typed for this queued message, or `undefined` when nothing is. */
export function queuedDraft(messageId: string): string | undefined {
  return drafts.get(messageId);
}

/** Record the current text of an open editor. */
export function rememberQueuedDraft(messageId: string, text: string): void {
  drafts.set(messageId, text);
}

/** The editor closed — saved, cancelled, or gone with its message. */
export function forgetQueuedDraft(messageId: string): void {
  drafts.delete(messageId);
}
