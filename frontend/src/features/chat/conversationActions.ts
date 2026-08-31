/**
 * What the operator can do to the *thread* — as opposed to a turn inside it.
 *
 * Rename lives in its own modal, but the rest of the session menu ends up here: retitle,
 * fork, copy, and the two deletes. Each is a confirm-or-probe, a call, and a toast, and
 * none of them belongs in the screen that lays out the conversation — the screen was
 * carrying a third of its length in error handling for actions it does not render.
 *
 * **A delete has to ask a second question first.** Images are shared: the same attachment
 * can be referenced from more than one place, so deleting the thread that happens to hold
 * one may strand it or may not. The backend is asked which images *this* delete would
 * orphan, and only when there are any does the operator get the three-way keep/purge
 * prompt — a plain confirm otherwise. A failed probe falls back to the plain confirm and
 * keeps the images: an unreachable answer is not a licence to delete more.
 *
 * **Stop the run before removing what it is writing into.** Aborting the local SSE does
 * not stop the run server-side, so a thread deleted mid-turn would keep generating into a
 * conversation that no longer exists.
 */

import { createSignal, type Accessor } from "solid-js";
import { isApiError } from "~/lib/api";
import { confirm, confirmChoice, copyToClipboard, toast } from "~/ui";
import { assembleTranscript } from "./blocks";
import {
  deleteConversation,
  fetchOrphanImageAttachments,
  forkConversation,
  regenerateTitle,
} from "./data";
import type { ChatMessage } from "./model";

/** Flatten the whole thread to plain text for COPY CONVERSATION — each turn's
 *  role and content in order, assistant turns including their tool calls/
 *  results via `assembleTranscript` (same shaping as per-message COPY
 *  MESSAGE), separated by rules so the export reads as a transcript. */
export function buildConversationTranscript(messages: ChatMessage[]): string {
  return messages
    .map((m) => {
      // A compaction divider is neither party's words — label it as the chassis note it
      // is rather than attributing the summary to the assistant.
      const label =
        m.role === "user"
          ? "Operator"
          : m.role === "compaction"
            ? "Context compacted"
            : "Assistant";
      const body =
        m.role === "assistant" ? assembleTranscript(m.blocks) : m.content;
      return `${label} · ${m.createdAt}\n${body}`;
    })
    .join("\n\n---\n\n");
}

export interface ConversationActionDeps {
  /** The open thread, or null when the composer is staging a new one. */
  conversationId: () => string | null;
  /** The transcript, for the clipboard export. */
  messages: ChatMessage[];
  /** Whether a turn is in flight — a delete has to stop it first. */
  sending: () => boolean;
  cancel: () => Promise<void>;
  removeMessage: (messageId: string, purgeImages: boolean) => Promise<void>;
  /** The open thread is gone; the room stages a new one. */
  onDeleted: () => void;
  /** The fork's id — the room opens it, leaving the source untouched. */
  onForked: (conversationId: string) => void;
}

export interface ConversationActions {
  /** True while a manual title regeneration is in flight — the header's throbber. */
  retitling: Accessor<boolean>;
  retitle: () => Promise<void>;
  fork: (messageId: string) => Promise<void>;
  removeConversation: () => Promise<void>;
  removeMessage: (messageId: string) => Promise<void>;
  copyTranscript: () => void;
}

export function createConversationActions(
  deps: ConversationActionDeps,
): ConversationActions {
  const [retitling, setRetitling] = createSignal(false);

  /** Gate a delete that may strand image attachments. Probes the backend for the
   *  images this delete would orphan; if any, raises the 3-way keep/purge prompt,
   *  otherwise the plain confirm. Returns the chosen `purgeImages`, or null to
   *  abort. A failed probe falls back to the plain confirm (keep images) so the
   *  delete stays usable. */
  async function resolveDeleteChoice(
    conversationId: string,
    title: string,
    baseDetail: string,
    messageId?: string,
  ): Promise<boolean | null> {
    let orphans: string[] = [];
    try {
      orphans = await fetchOrphanImageAttachments(conversationId, messageId);
    } catch {
      // Probe failed — fall through to the plain confirm below.
    }
    if (orphans.length === 0) {
      const ok = await confirm({
        title,
        detail: baseDetail,
        confirmLabel: "Delete",
        tone: "alert",
      });
      return ok ? false : null;
    }
    const n = orphans.length;
    const choice = await confirmChoice({
      title,
      detail: `${baseDetail} ${n} image attachment${
        n > 1 ? "s" : ""
      } would be left unused — delete them too, or keep them?`,
      confirmLabel: "Delete images",
      secondaryLabel: "Keep images",
      cancelLabel: "Cancel",
      tone: "alert",
    });
    if (choice === "cancel") return null;
    return choice === "primary";
  }

  async function retitle(): Promise<void> {
    const id = deps.conversationId();
    if (!id || retitling()) return;
    setRetitling(true);
    try {
      await regenerateTitle(id);
      toast.success("Title regenerated");
    } catch {
      toast.error("Unable to regenerate the title.");
    } finally {
      setRetitling(false);
    }
  }

  /** Open a new conversation carrying history up to this turn.
   *
   *  The backend returns the *fork's* detail, so the room reseats onto the new id
   *  rather than reloading the source and hunting for it. The source thread is
   *  untouched, which is the whole point — a tangent shouldn't cost the
   *  conversation it came from. */
  async function fork(messageId: string): Promise<void> {
    const id = deps.conversationId();
    if (!id) return;
    try {
      deps.onForked(await forkConversation(id, messageId));
      toast.success("Forked into a new conversation.");
    } catch (err) {
      toast.error(
        isApiError(err) ? err.detail : "Unable to fork this conversation.",
      );
    }
  }

  async function removeConversation(): Promise<void> {
    const id = deps.conversationId();
    if (!id) return;
    const purgeImages = await resolveDeleteChoice(
      id,
      "Delete this conversation?",
      "This permanently removes the thread and its history.",
    );
    if (purgeImages === null) return;
    try {
      // Deleting a thread mid-stream must stop its generation: cancel the live
      // run first (while it still exists) so the backend halts it, rather than
      // leaving it generating into a conversation that's about to be gone —
      // aborting the local SSE alone wouldn't stop the run server-side.
      if (deps.sending()) await deps.cancel();
      await deleteConversation(id, purgeImages);
      deps.onDeleted();
      toast.success("Conversation deleted");
    } catch {
      toast.error("Unable to delete the conversation.");
    }
  }

  async function removeMessage(messageId: string): Promise<void> {
    const id = deps.conversationId();
    if (!id) return;
    const purgeImages = await resolveDeleteChoice(
      id,
      "Delete this message?",
      "This removes it and everything after it.",
      messageId,
    );
    if (purgeImages === null) return;
    await deps.removeMessage(messageId, purgeImages);
    toast.success("Message deleted");
  }

  return {
    retitling,
    retitle,
    fork,
    removeConversation,
    removeMessage,
    copyTranscript: () =>
      copyToClipboard(
        buildConversationTranscript(deps.messages),
        "Conversation",
      ),
  };
}
