/**
 * One conversation: how it is read, and everything the operator can do to it that isn't a
 * turn.
 *
 * Renaming, retitling, forking, deleting, revoking a grant, forcing compaction on or off —
 * each is a thin relay to a live endpoint, and each ends by telling the list to re-read
 * itself rather than patching a second copy of the truth locally. That is the rule this
 * module exists to keep: the backend owns a conversation's state, and the client's job is
 * to ask again, not to guess what the answer became.
 */

import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { sessionMode } from "~/lib/modes";
import type { PlanItem } from "~/lib/stream";
import {
  permissionLevel,
  type ApprovalGrant,
  type ChatSession,
  type CompactionState,
} from "../model";
import {
  deriveTitle,
  toActiveRun,
  toMessage,
  toStats,
  toViewSnapshotRef,
} from "./mappers";
import { refreshSessions } from "./sessions";
import { revealTitle } from "./titleReveals";
import type {
  ApprovalGrantDTO,
  ConversationDetailDTO,
  ConversationSummaryDTO,
  OrphanImageAttachmentsDTO,
} from "./wire";

async function fetchSession(id: string): Promise<ChatSession> {
  const dto = await api.get<ConversationDetailDTO>(`/conversations/${id}`);
  return {
    id: dto.id,
    title: deriveTitle(dto),
    messages: dto.messages.map(toMessage),
    context: dto.context,
    stats: dto.stats ? toStats(dto.stats) : null,
    activeRun: toActiveRun(dto.active_run),
    snapshots: (dto.snapshots ?? []).map(toViewSnapshotRef),
    mode: sessionMode(dto.mode ?? undefined),
    permission: permissionLevel(dto.permission_level ?? undefined),
  };
}

/** Loads a session. A null id means a new, unsaved conversation — the resource
 *  doesn't fetch, so the screen renders an empty thread. */
export function useChatSession(id: () => string | null): Resource<ChatSession> {
  const [data] = createResource(id, fetchSession);
  return data;
}

export async function renameConversation(
  id: string,
  title: string,
): Promise<void> {
  await api.patch(`/conversations/${id}`, { title });
  refreshSessions();
}

/** Re-derive a thread's title on demand. The backend names it from every question
 *  the operator asked across the thread (not just the opening line, and never the
 *  assistant's replies), then this reveals the result with the same typewriter
 *  animation as the first-turn auto-title so both surfaces stay in lockstep. */
export async function regenerateTitle(id: string): Promise<void> {
  // Titling resolves the backend `utility`→`main` binding (with its pinned model),
  // the same source every background caller uses — no per-request override needed.
  const summary = await api.post<ConversationSummaryDTO>(
    `/conversations/${id}/retitle`,
    {},
  );
  if (summary.title) revealTitle(id, summary.title);
  refreshSessions();
}

export async function deleteConversation(
  id: string,
  purgeImages = false,
  discardBranch = false,
): Promise<void> {
  const params = [
    purgeImages ? "purgeImages=true" : "",
    // A code thread with unmerged commits is refused unless this says so —
    // the backend decides, this only relays the operator's answer.
    discardBranch ? "discardBranch=true" : "",
  ].filter(Boolean);
  const q = params.length ? `?${params.join("&")}` : "";
  await api.del(`/conversations/${id}${q}`);
  refreshSessions();
}

/** Copy a thread's history up to `messageId` into a new conversation and return
 *  its id. The backend returns the *fork's* detail, so the caller navigates in one
 *  round-trip; the source thread is untouched. */
export async function forkConversation(
  conversationId: string,
  messageId: string,
): Promise<string> {
  const detail = await api.post<ConversationDetailDTO>(
    `/conversations/${conversationId}/messages/${messageId}/fork`,
    {},
  );
  refreshSessions();
  return detail.id;
}

/** Image uploads a pending delete would orphan — ones nothing else references.
 *  Probed before a conversation/message delete so the operator can be offered the
 *  keep-or-purge choice. Empty ⇒ nothing would be left unused, delete outright.
 *  Omit `messageId` for a whole-conversation delete. */
export async function fetchOrphanImageAttachments(
  conversationId: string,
  messageId?: string,
): Promise<string[]> {
  const q = messageId ? `?messageId=${encodeURIComponent(messageId)}` : "";
  const res = await api.get<OrphanImageAttachmentsDTO>(
    `/conversations/${conversationId}/orphan-image-attachments${q}`,
  );
  return res.upload_ids;
}

// Bumped when an approval is submitted that records a conversation grant, so the
// AUTO-APPROVED strip refetches at approve time rather than waiting for the next
// stream-state toggle (the run is already mid-flight when the grant is made).
const [grantsRevision, setGrantsRevision] = createSignal(0);
export const conversationGrantsRevision = grantsRevision;

/** Tell the AUTO-APPROVED strip a grant was just recorded, so it refetches now
 *  rather than at the next stream-state toggle. */
export function bumpGrantsRevision(): void {
  setGrantsRevision((n) => n + 1);
}

/** The tools the operator allowed to auto-approve for the rest of this conversation. */
export async function fetchGrants(
  conversationId: string,
): Promise<ApprovalGrant[]> {
  const rows = await api.get<ApprovalGrantDTO[]>(
    `/conversations/${conversationId}/grants`,
  );
  return rows.map((r) => ({ toolName: r.tool_name }));
}

/** The agent's task list for a thread.
 *
 *  The list also arrives live on `plan.updated`, but a client opening or reloading a
 *  conversation has no stream to replay — this is how the panel starts from the truth
 *  instead of staying empty until the next mutation.
 */
export async function fetchPlan(conversationId: string): Promise<PlanItem[]> {
  return api.get<PlanItem[]>(`/conversations/${conversationId}/plan`);
}

/** The stream path for this thread's live agent browser, or null when it has none.
 *
 *  The `browser.live` event announces a session as the agent first touches a page, but a
 *  client that reloads (or opens the thread later) has no stream to replay and the
 *  session outlives the run that announced it — so the backend's session manager, not the
 *  transcript, is what the panel starts from.
 */
export async function fetchBrowserSession(
  conversationId: string,
): Promise<string | null> {
  const info = await api.get<{ active: boolean; url: string | null }>(
    `/browser/session/${conversationId}`,
  );
  return info.active ? info.url : null;
}

/** Revoke a conversation auto-approval — the next call to that tool asks again. */
export async function revokeGrant(
  conversationId: string,
  toolName: string,
): Promise<void> {
  await api.del(
    `/conversations/${conversationId}/grants/${encodeURIComponent(toolName)}`,
  );
}

/** This conversation's compaction state (its override + the resolved effective on/off) —
 *  folding older turns into a summary once the context window fills. The only reduction
 *  there is; per-tool-result digesting was removed. */
export async function fetchAutoCompactOverride(
  conversationId: string,
): Promise<CompactionState> {
  return api.get<CompactionState>(
    `/conversations/${conversationId}/auto-compact`,
  );
}

/** Force conversation compaction on/off for this chat (or `null` to inherit the global
 *  setting); returns the new state. */
export async function setAutoCompactOverride(
  conversationId: string,
  override: boolean | null,
): Promise<CompactionState> {
  return api.put<CompactionState>(
    `/conversations/${conversationId}/auto-compact`,
    { override },
  );
}
