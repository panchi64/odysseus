/**
 * The composer as the third surface that edits a queued message.
 *
 * ArrowUp in an empty composer opens the newest queued operator message in the field
 * itself — the way a shell recalls its last command — so correcting what was just sent
 * does not mean reaching for the bubble up-thread. It is the same act the bubble and
 * the dock's list offer, so it follows the same protocol: one `createQueuedEdit`, whose
 * target is swapped as the arrows walk the queue. The hold is taken before the first
 * keystroke and released on every way out, and the draft is published for the run's
 * teardown, exactly as on the other two surfaces — none of it restated here.
 *
 * What this adds is only what is particular to a field that is *borrowed*: which message
 * the arrows land on (`queuedRecall.ts`), and leaving when that message stops being
 * queued underneath the operator.
 */

import { createEffect, createSignal, untrack } from "solid-js";
import type { ComposerRecallApi } from "~/ui";
import type { ChatMessage } from "./model";
import { createQueuedEdit } from "./queuedEdit";
import { recallStep, type RecallDirection } from "./queuedRecall";

export interface ComposerRecallDeps {
  messages: readonly ChatMessage[];
  editQueued: (queuedMessageId: string, text: string) => void;
  holdQueued: (queuedMessageId: string, held: boolean) => void;
  /** Hand text back to the composer's own draft. */
  stash: (text: string) => void;
}

/** A message the operator queued into the live run and that is still waiting — never a
 *  sub-agent's report, which queues on the same road and is neither theirs to rewrite
 *  nor to take back (the rule `restoreUndelivered` keeps). One predicate for every
 *  surface that lists or walks them, so they cannot disagree about which are waiting. */
export const isOperatorQueued = (m: ChatMessage): boolean =>
  Boolean(m.queuedPending) && m.role === "user";

/** The operator's queued message ids, in transcript order. */
const queuedIds = (messages: readonly ChatMessage[]): string[] =>
  messages.flatMap((m) =>
    isOperatorQueued(m) && m.queuedMessageId ? [m.queuedMessageId] : [],
  );

export function createComposerRecall(
  deps: ComposerRecallDeps,
): ComposerRecallApi {
  const [target, setTarget] = createSignal<string | null>(null);
  const message = () => {
    const id = target();
    return id === null
      ? undefined
      : deps.messages.find((m) => m.queuedMessageId === id);
  };

  const edit = createQueuedEdit({
    messageId: () => target() ?? undefined,
    queued: () => message()?.queuedPending === true,
    initial: () => message()?.content ?? "",
    onHold: (held) => {
      const id = target();
      if (id) deps.holdQueued(id, held);
    },
    onSave: (text) => {
      const id = target();
      if (id) deps.editQueued(id, text);
    },
  });

  /** Leave without committing. Guarded, because closing an edit that is not open would
   *  still tell the run to stop holding a message nobody asked it to hold. */
  const cancel = (): void => {
    if (edit.editing()) edit.cancel();
    setTarget(null);
  };

  const open = (id: string): void => {
    setTarget(id);
    edit.start();
  };

  const step = (direction: RecallDirection): boolean => {
    const current = edit.editing() ? target() : null;
    // An edit with changes in it is not walked away from: the arrows at the field's
    // edges are also plain caret keys, and one pressed on the way to the first line
    // would otherwise throw the rewrite away. Save or Escape leave it; the arrows
    // resume once it matches what was sent.
    if (current !== null && edit.draft() !== (message()?.content ?? ""))
      return false;
    const next = recallStep(queuedIds(deps.messages), current, direction);
    // Nothing older: stay on the one that is open. Nothing newer: step out, which is a
    // move — the field goes back to the operator's own draft.
    if (next === null && direction === "older") return false;
    if (next === null && current === null) return false;
    cancel();
    if (next !== null) open(next);
    return true;
  };

  // The message stopped being queued underneath the edit. Read as three cases, because
  // they differ in who already has the operator's typing:
  //  - the run ended: `restoreUndelivered` removed the bubble and has already handed the
  //    published draft to the composer's prefill — handing it back again would double it;
  //  - withdrawn: removed on purpose, so what was being typed over it goes with it;
  //  - injected before the hold landed: the bubble stays, delivered with its old text,
  //    and the typing has no other way back — so it goes into the composer's own draft.
  createEffect(() => {
    if (!edit.editing()) return;
    const m = message();
    if (m?.queuedPending) return;
    untrack(() => {
      const typed = edit.draft().trim();
      cancel();
      if (m && typed && typed !== m.content.trim()) deps.stash(typed);
    });
  });

  // No cleanup of its own: `createQueuedEdit` releases the hold when this owner goes, and
  // it reads the target *as* it closes — resetting the target here first would leave it
  // closing an edit on no message, and the hold would outlive the room.

  return {
    draft: () => (edit.editing() ? edit.draft() : null),
    label: "Editing queued message",
    step,
    write: edit.write,
    save: () => {
      edit.save();
      setTarget(null);
    },
    cancel,
  };
}
