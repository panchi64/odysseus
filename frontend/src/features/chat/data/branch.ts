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

/** One changed file, as the backend ranked it.
 *
 *  **Every judgement here is the server's.** `category`, `risk` and `reason` are
 *  computed in `services/projects` and sent down finished — the frontend must not infer
 *  a band from a path, re-word a reason, or decide that a lockfile matters. It renders
 *  what it was handed, which is the same rule the review card keeps about a verdict. */
export interface FileChange {
  /** The file's path **now**. For a rename, where it ended up. */
  path: string;
  /** Where a rename came from; null for everything else. */
  oldPath: string | null;
  status:
    | "added"
    | "modified"
    | "deleted"
    | "renamed"
    | "copied"
    | "type-changed"
    | "unmerged";
  insertions: number;
  deletions: number;
  /** True when git could not count lines — in which case the two numbers above mean
   *  nothing and must not be printed as a diffstat. */
  binary: boolean;
  category:
    | "dependency"
    | "infrastructure"
    | "config"
    | "code"
    | "test"
    | "asset"
    | "docs";
  risk: "high" | "elevated" | "normal";
  /** One server-authored phrase saying why this file is banded where it is. **Shown
   *  verbatim** — it is the backend speaking, not a key to look a sentence up by. */
  reason: string;
}

/** What a code thread has changed against its project's base ref.
 *
 *  **`files` arrives sorted and the order is part of the contract** — risk, then
 *  category, then churn, then path. Render it in the order given: re-sorting it in the
 *  browser would be the frontend re-deciding a verdict the backend already reached. */
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
  /** Per-file rows, pre-ranked. Empty when there is no branch yet. */
  files: FileChange[];
  /** Commits the branch has that the base does not. 0 when unknown. */
  ahead: number;
  /** Commits the base has that the branch does not — **the staleness number**. 0 when
   *  unknown, which is why the chip reports it on `> 0` rather than on presence. */
  behind: number;
  /** The branch tip's committer date, ISO-8601 **with an offset**; null when there is
   *  no branch. A string and not a date: it is git's own field passed through. */
  lastCommitAt: string | null;
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
