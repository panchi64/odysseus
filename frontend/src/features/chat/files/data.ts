/** The `@` picker's seam — one read, mapped, nothing decided here.
 *
 *  Matching and ranking are the backend's: a path is mostly directory names, and which
 *  of two files a query meant is a rule that has to agree with the one the reference is
 *  later resolved by. Sending the query rather than filtering a cached list is also what
 *  keeps a large repository from arriving in the browser.
 */

import { createResource, type Resource } from "solid-js";
import { api } from "~/lib/api";

export interface ProjectFile {
  /** Relative to the listed root, forward slashes — the string a reference carries. */
  path: string;
  name: string;
}

export interface ProjectFiles {
  /** Which filesystem answered: the thread's own worktree, or the operator's checkout
   *  (what a code thread lists before its first turn has created a worktree). */
  root: "worktree" | "project";
  entries: ProjectFile[];
  truncated: boolean;
}

const EMPTY: ProjectFiles = { root: "project", entries: [], truncated: false };

async function fetchFiles(
  key: readonly [string | null, string | null, string],
): Promise<ProjectFiles> {
  const [projectId, conversationId, query] = key;
  if (!projectId) return EMPTY;
  const params = new URLSearchParams({ query });
  // Presence, not identity: naming a thread asks for its worktree, and the backend
  // hands back the project root whenever there isn't one yet.
  if (conversationId) params.set("conversation_id", conversationId);
  return await api.get<ProjectFiles>(`/projects/${projectId}/files?${params}`);
}

/** Files this thread can reference, for the current query. */
export function useProjectFiles(
  projectId: () => string | null,
  conversationId: () => string | null,
  query: () => string | null,
): Resource<ProjectFiles> {
  const [data] = createResource(
    () => {
      const q = query();
      // A null query means the menu is closed — no source, so no fetch at all.
      return q === null ? false : ([projectId(), conversationId(), q] as const);
    },
    (key) => fetchFiles(key),
  );
  return data;
}
