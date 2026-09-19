/**
 * Cross-surface entry intents — what the chat room should do the moment it mounts.
 *
 * The overview launchpad, a task's run history and a notification's deep-link all want the
 * same two things: open *that* thread, or start a new one with *this* draft already
 * written. None of them can hand it over directly — they unmount as the room mounts — so
 * the intent is parked here and consumed once on arrival.
 *
 * Deliberately consume-once (`consume*` clears as it reads): an intent that survived its
 * first read would re-fire on the next navigation, re-opening a thread the operator had
 * just left or resurrecting a draft they already sent.
 */

import { createSignal } from "solid-js";
import type { ModelSelection } from "~/lib/stores/models";
import type { PermissionLevel } from "../model";
import type { CommandInvocation } from "../commands/model";

interface PendingDraft {
  text: string;
  model: ModelSelection | null;
  /** Ids of uploads attached on the launchpad, carried into the first turn. */
  attachmentIds?: string[];
  /** A `/` command picked on the launchpad. It has to ride the handoff or it is lost:
   *  the launchpad unmounts as the room mounts, and the room would receive the operator's
   *  literal `/reviewer …` with nothing saying what that token was. */
  command?: CommandInvocation | null;
  /** A level picked with `/level` on the launchpad. The one action command that is
   *  offered without a thread and has nowhere to write until one exists — so it is staged
   *  here and applied as the thread is created, which is exactly what the command's own
   *  description already promises ("rides the next send"). */
  permissionLevel?: PermissionLevel;
}

const [_pendingDraft, _setPendingDraft] = createSignal<PendingDraft | null>(
  null,
);

export function startConversation(
  text: string,
  model: ModelSelection | null,
  attachmentIds?: string[],
  extras?: {
    command?: CommandInvocation | null;
    permissionLevel?: PermissionLevel;
  },
): void {
  _setPendingDraft({ text, model, attachmentIds, ...extras });
}
export function consumePendingDraft(): PendingDraft | null {
  const v = _pendingDraft();
  if (v) _setPendingDraft(null);
  return v;
}

const [_requestedSession, _setRequestedSession] = createSignal<string | null>(
  null,
);
export function openConversation(id: string): void {
  _setRequestedSession(id);
}
export function consumeRequestedSession(): string | null {
  const v = _requestedSession();
  if (v) _setRequestedSession(null);
  return v;
}
