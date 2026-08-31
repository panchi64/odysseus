/**
 * A code thread's git branch — what it has changed, and the two ways it ends.
 *
 * Only a code thread has one: it works in a worktree cut from a project's repository, and
 * the header's chip is the operator's view of what has accumulated there. Every other
 * conversation has no branch at all, which is why the read degrades rather than errors.
 *
 * **A 404 is the ordinary answer, not a failure.** So is a project directory the operator
 * has since moved. Either way the chip disappears and the header stays — a thread's
 * transcript must not become unreadable because its worktree went missing.
 */

import { api, isApiError } from "~/lib/api";

/** What a code thread has changed against its project's base ref. */
export interface BranchState {
  conversationId: string;
  projectId: string;
  branch: string;
  baseRef: string;
  filesChanged: number;
  insertions: number;
  deletions: number;
  patch: string;
  active: boolean;
}

/** The thread's branch, or null when there isn't one to show. */
export async function fetchBranch(
  conversationId: string,
): Promise<BranchState | null> {
  try {
    return await api.get<BranchState>(`/worktrees/${conversationId}`);
  } catch (err) {
    if (!isApiError(err) || err.status !== 404) {
      console.warn("branch state unavailable", err);
    }
    return null;
  }
}

export async function mergeBranch(conversationId: string): Promise<string> {
  const res = await api.post<{ merged: boolean; detail: string }>(
    `/worktrees/${conversationId}/merge`,
    {},
  );
  return res.detail;
}

export async function discardBranch(conversationId: string): Promise<void> {
  await api.post(`/worktrees/${conversationId}/discard`, {});
}
