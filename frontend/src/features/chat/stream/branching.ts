/**
 * What the operator can do to a turn that has already been recorded.
 *
 * Regenerate, edit, cycle versions, rewind, compact, delete, pin, bookmark a snapshot —
 * all of them act on the *conversation tree* rather than on the run in flight, which is
 * why they live apart from the controller that drives a run. Each is a thin relay to a
 * live endpoint, and each ends the same way: the backend returns the new active path and
 * the store is reseated from it, so what the transcript shows after the action is exactly
 * what a cold read would give.
 *
 * **Reseat, don't patch.** The two ops that stream (regenerate/edit) optimistically reset
 * the path *before* the run so the operator sees the turn clear immediately; the rest wait
 * for the backend's answer. Neither tries to compute the resulting tree locally — a second
 * implementation of the branch arithmetic is exactly the kind of thing that agrees with the
 * backend until the day it doesn't.
 *
 * **Cancel first, then mutate.** A live fold keeps patching the message it was streaming
 * into, so an op that replaces the store while a run is open would leave the fold writing
 * to a message that no longer exists. Every reseating op therefore stops the run first.
 */

import { reconcile, type SetStoreFunction } from "solid-js/store";
import type { Setter } from "solid-js";
import { api, isApiError } from "~/lib/api";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import { toast } from "~/ui";
import { toMessage, toViewSnapshotRef } from "../data/mappers";
import type { ChatCreatedDTO, ConversationDetailDTO } from "../data/wire";
import type { ChatMessage, ContextUsage, ViewSnapshotRef } from "../model";
import { nextId } from "./patch";

/** The store slots a conversation detail reseats — the active path, the window
 *  reading that moved with it, and the conversation-scoped snapshot history. */
export interface TranscriptStore {
  setMessages: SetStoreFunction<ChatMessage[]>;
  setUsage: Setter<ContextUsage | null>;
  setSnapshots: Setter<ViewSnapshotRef[]>;
}

/** Replace the transcript with the backend's active path. Shared by the branching ops
 *  and by the controller's own reconciliation points, so a reload, a version switch and
 *  a recovered stale decision all land on the identical shape. */
export function reseatFromDetail(
  store: TranscriptStore,
  detail: ConversationDetailDTO,
): void {
  // The same mapper the cold read uses, which is the point: a reseat has to produce
  // exactly the transcript a reload would.
  store.setMessages(reconcile(detail.messages.map(toMessage)));
  // The active path moved (version switch / rewind / delete), so the window
  // state moves with it.
  store.setUsage(detail.context);
  // Re-seed the conversation-level snapshot history from the same detail.
  store.setSnapshots((detail.snapshots ?? []).map(toViewSnapshotRef));
}

/** Everything the branching ops need from the controller they belong to. Passed in
 *  rather than closed over, so the ops read as relays to the backend instead of as
 *  another part of the run-driving closure. */
export interface BranchingContext extends TranscriptStore {
  messages: ChatMessage[];
  /** The conversation the stream is bound to right now — a getter, because `send`
   *  adopts a freshly-created thread's id mid-flight. */
  conversationId: () => string | null;
  sending: () => boolean;
  setSending: (value: boolean) => void;
  patchById: (id: string, fn: (m: ChatMessage) => void) => void;
  /** The per-instance model override (the compare panes), or undefined when this
   *  stream follows the global picker. */
  overrideSelection: () => ModelSelection | null | undefined;
  driveRun: (runId: string, assistantId: string) => Promise<void>;
  reattachToLiveRun: (conversationId: string) => Promise<void>;
  cancel: () => Promise<void>;
  onTurnComplete?: () => void;
}

function toastError(err: unknown, fallback: string): void {
  toast.error((err as { detail?: string })?.detail ?? fallback);
}

export function createBranchingOps(ctx: BranchingContext) {
  const reseat = (detail: ConversationDetailDTO) =>
    reseatFromDetail(ctx, detail);

  /** A 409 means the backend already has a run on this thread. Surface the one that is
   *  actually in flight instead of leaving the operator's action to vanish. */
  function handleBusy(err: unknown): boolean {
    if (!isApiError(err) || err.status !== 409) return false;
    toast.error("A response is still in progress in this conversation.");
    ctx.setSending(false);
    const id = ctx.conversationId();
    if (id) void ctx.reattachToLiveRun(id);
    return true;
  }

  /** Re-answer an assistant turn from the preceding request, using the current
   *  model selection; the new answer becomes a sibling version. `messageId` is
   *  the assistant message's id. */
  async function regenerate(messageId: string): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null || ctx.sending()) return;
    const i = ctx.messages.findIndex(
      (m) => m.id === messageId && m.role === "assistant",
    );
    if (i < 0) return;
    ctx.setSending(true);
    const override = ctx.overrideSelection();
    const sel = override ?? effectiveSelection();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/regenerate", {
        conversation_id: conversationId,
        message_id: messageId,
        endpoint_id: override?.endpointId,
        model: override?.model,
      });
      const reset: ChatMessage = {
        id: messageId,
        role: "assistant",
        model: sel?.model,
        content: "",
        blocks: [],
        streaming: true,
        queued: true,
        createdAt: new Date().toISOString(),
      };
      ctx.setMessages(reconcile([...ctx.messages.slice(0, i), reset]));
      await ctx.driveRun(created.run_id, messageId);
    } catch (err) {
      if (handleBusy(err)) return;
      toastError(err, "Unable to regenerate the answer.");
      ctx.setSending(false);
    }
  }

  /** Re-ask an edited user turn as a new version; a fresh answer streams in.
   *  `messageId` is the user message's id. */
  async function edit(
    messageId: string,
    newText: string,
    selection?: ModelSelection | null,
    attachmentIds?: string[],
  ): Promise<void> {
    const conversationId = ctx.conversationId();
    const j = ctx.messages.findIndex(
      (m) => m.id === messageId && m.role === "user",
    );
    if (j < 0 || conversationId === null || ctx.sending()) return;
    // Reuse the turn's existing attachments unless the caller supplies a new set.
    const ids = attachmentIds ?? ctx.messages[j].attachmentIds ?? [];
    if (!newText.trim() && ids.length === 0) return;
    ctx.setSending(true);
    const override = selection ?? ctx.overrideSelection();
    const sel = override ?? effectiveSelection();
    const prompt = newText.trim();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/edit", {
        conversation_id: conversationId,
        message_id: messageId,
        prompt,
        endpoint_id: override?.endpointId,
        model: override?.model,
        attachment_ids: ids,
      });
      const editedUser: ChatMessage = {
        ...ctx.messages[j],
        content: prompt,
        attachmentIds: ids.length ? ids : undefined,
      };
      const assistantId = nextId("a");
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        model: sel?.model,
        content: "",
        blocks: [],
        streaming: true,
        queued: true,
        createdAt: new Date().toISOString(),
      };
      ctx.setMessages(
        reconcile([...ctx.messages.slice(0, j), editedUser, assistantMsg]),
      );
      await ctx.driveRun(created.run_id, assistantId);
    } catch (err) {
      if (handleBusy(err)) return;
      toastError(err, "Unable to submit the edit.");
      ctx.setSending(false);
    }
  }

  /** Switch a turn to a sibling version; reseat the store from the returned
   *  active path and refresh the sidebar. */
  async function switchVersion(
    messageId: string,
    index: number,
  ): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null) return;
    // Stop any live run first: the reseat below replaces the store, and a still-
    // streaming foldEvent would keep patching a message the reseat removed.
    if (ctx.sending()) await ctx.cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${conversationId}/messages/${messageId}/version`,
        { index },
      );
      reseat(detail);
      ctx.onTurnComplete?.();
    } catch (err) {
      toastError(err, "Unable to switch versions.");
    }
  }

  /** Rewind the thread to end at a turn; the operator's next send branches. */
  async function rewind(messageId: string): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null) return;
    if (ctx.sending()) await ctx.cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${conversationId}/messages/${messageId}/rewind`,
        {},
      );
      reseat(detail);
      ctx.onTurnComplete?.();
      toast.success("Rewound — your next message starts a new branch");
    } catch (err) {
      toastError(err, "Unable to rewind the conversation.");
    }
  }

  /** Fold this thread's older turns into a summary now, rather than waiting for it to
   *  reach the automatic threshold — for a thread the operator knows is about to need the
   *  room. Reseats from the returned active path like the other transcript-mutating
   *  actions, so the new divider renders from exactly the shape a cold read gives. */
  async function compactNow(): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null) return;
    if (ctx.sending()) await ctx.cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${conversationId}/compact`,
        {},
      );
      reseat(detail);
      toast.success("Earlier turns folded into a summary");
    } catch (err) {
      toastError(err, "Unable to compact this conversation.");
    }
  }

  /** Delete a turn and everything after it; reseat from the returned active path
   *  (the DELETE returns the post-delete detail, like version-switch/rewind). */
  async function removeMessage(
    messageId: string,
    purgeImages = false,
  ): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null) return;
    if (ctx.sending()) await ctx.cancel();
    try {
      const q = purgeImages ? "?purgeImages=true" : "";
      const detail = await api.del<ConversationDetailDTO>(
        `/conversations/${conversationId}/messages/${messageId}${q}`,
      );
      reseat(detail);
      ctx.onTurnComplete?.();
    } catch (err) {
      toastError(err, "Unable to delete the message.");
    }
  }

  /** Pin/unpin a turn. The backend owns the flag; this optimistically echoes the
   *  toggle and reverts if the POST fails. */
  async function toggleMessagePin(messageId: string): Promise<void> {
    const conversationId = ctx.conversationId();
    if (conversationId === null) return;
    const msg = ctx.messages.find((m) => m.id === messageId);
    if (!msg) return;
    const next = !msg.pinned;
    ctx.patchById(messageId, (m) => {
      m.pinned = next;
    });
    try {
      await api.post(
        `/conversations/${conversationId}/messages/${messageId}/pin`,
        { pinned: next },
      );
    } catch (err) {
      ctx.patchById(messageId, (m) => {
        m.pinned = !next;
      });
      toastError(err, "Unable to update the pin.");
    }
  }

  /** Flip a snapshot's keeper bookmark: optimistically replace the array element
   *  (a spread copy — never mutate the stored ref in place), then confirm against
   *  the backend, reverting the same way on failure. */
  async function toggleSnapshotKeeper(
    snapshotId: string,
    keeper: boolean,
  ): Promise<void> {
    ctx.setSnapshots((prev) =>
      prev.map((s) => (s.snapshotId === snapshotId ? { ...s, keeper } : s)),
    );
    try {
      await api.post(`/views/snapshots/${snapshotId}/keeper`, { keeper });
    } catch (err) {
      ctx.setSnapshots((prev) =>
        prev.map((s) =>
          s.snapshotId === snapshotId ? { ...s, keeper: !keeper } : s,
        ),
      );
      toastError(err, "Unable to update the keeper flag.");
    }
  }

  return {
    regenerate,
    edit,
    switchVersion,
    rewind,
    compactNow,
    removeMessage,
    toggleMessagePin,
    toggleSnapshotKeeper,
  };
}
