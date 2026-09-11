/**
 * A code thread's branch, fetched once for everyone who wants it.
 *
 * The header's chip owned this resource, which was right while the chip was the only
 * thing that showed a branch. The Diff surface shows the same patch, and two components
 * each holding their own `createResource` over `/worktrees/{id}` means two fetches of the
 * same bytes and — worse — two answers that can disagree for as long as one of them is
 * still in flight.
 *
 * So the room creates it once and hands it to both. Nothing else changes: the read still
 * degrades to `null` rather than erroring, because a thread with no worktree is the
 * ordinary case and its transcript must not become unreadable when the answer is 404.
 */

import { createResource, type Resource } from "solid-js";
import { fetchBranch, type BranchState } from "./data";

export interface BranchStateApi {
  /** The branch, or null when this thread has none. */
  branch: Resource<BranchState | null>;
  /** What both consumers should read while a re-fetch is in flight — see below. */
  latest: () => BranchState | null | undefined;
  refetch: () => void;
}

/**
 * `revision` is bumped by the caller when a turn settles, since that is when the agent
 * has just changed something.
 *
 * **`latest`, not the resource's own value.** A plain read goes `undefined` for the
 * length of a refetch, so the chip blinked out of the header and back in at exactly the
 * moment the operator looks up from a finished answer. `.latest` holds the previous
 * diffstat until the new one lands, which is also the more honest thing to show: the
 * branch did not stop existing while we asked about it.
 */
export function createBranchState(
  conversationId: () => string | null,
  revision: () => number,
): BranchStateApi {
  const [branch, { refetch }] = createResource(
    () => {
      const id = conversationId();
      return id === null ? undefined : ([id, revision()] as const);
    },
    ([id]) => fetchBranch(id),
  );
  return {
    branch,
    latest: () => branch.latest,
    refetch: () => void refetch(),
  };
}
