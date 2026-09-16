/**
 * Editing a message that is still queued on a live run — the rule, without the markup.
 *
 * Two surfaces edit the same thing: the queued bubble in the transcript, and the row the
 * approval dock lists while a park holds the composer's slot. They look nothing alike —
 * one is the operator's own turn at reading size, the other a line in a panel — so they
 * are not one component with a variant. What they must not differ on is the *protocol*,
 * which is three rules and easy to half-implement:
 *
 *   1. **Take the hold before the first keystroke.** The race is with the run's next model
 *      call, not with the operator's typing: by the time they have written anything the
 *      message may already have been injected and the edit lost.
 *   2. **Release it on every way out** — saved, cancelled, or the surface unmounted under
 *      them. The hold stops the run draining, so a forgotten one stalls the queue with
 *      nothing on screen to explain the stall.
 *   3. **Publish the draft** (`queuedDraft.ts`), because a run that ends mid-edit hands
 *      undelivered text back to the composer and must hand back what is being typed
 *      rather than the text it is replacing.
 *
 * It is state only: no fetch, no timer, no DOM. What `onEdit`/`onHold` actually do is the
 * consuming layer's business.
 */

import { createSignal, onCleanup, type Accessor } from "solid-js";
import { forgetQueuedDraft, rememberQueuedDraft } from "./queuedDraft";

export interface QueuedEditDeps {
  /** The backend id of the queued message, or `undefined` for a message that is not
   *  queued — a delivered turn being re-asked has no queue entry to hold. */
  messageId: Accessor<string | undefined>;
  /** Whether it is still queued *right now*. Read at the moment of each act rather than
   *  captured, because a message can be injected while its editor is open. */
  queued: Accessor<boolean>;
  /** The text the editor opens on. */
  initial: Accessor<string>;
  /** Commit. Called with the trimmed text, never with an empty one. */
  onSave: (text: string) => void;
  /** Ask the run to hold this message back, or to stop. */
  onHold?: (held: boolean) => void;
}

export interface QueuedEdit {
  editing: Accessor<boolean>;
  draft: Accessor<string>;
  /** A keystroke. */
  write: (text: string) => void;
  start: () => void;
  /** Leave without committing — and leave the queue moving again. */
  cancel: () => void;
  save: () => void;
}

export function createQueuedEdit(deps: QueuedEditDeps): QueuedEdit {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");

  const write = (text: string): void => {
    setDraft(text);
    const id = deps.messageId();
    if (id && deps.queued()) rememberQueuedDraft(id, text);
  };

  const close = (): void => {
    setEditing(false);
    const id = deps.messageId();
    if (!id) return;
    forgetQueuedDraft(id);
    if (deps.queued()) deps.onHold?.(false);
  };

  const start = (): void => {
    write(deps.initial());
    setEditing(true);
    if (deps.queued()) deps.onHold?.(true);
  };

  const save = (): void => {
    const text = draft().trim();
    if (text) deps.onSave(text);
    close();
  };

  onCleanup(() => {
    if (editing()) close();
  });

  return { editing, draft, write, start, cancel: close, save };
}
