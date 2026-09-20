/**
 * The workspace as it stands right now, rather than as it was last captured.
 *
 * The Files panel used to read a **View snapshot**, which only exists once the agent has
 * called `view_show`. A code thread that never minted one showed an empty panel while its
 * worktree sat full of files — so the panel now reads the same listing the composer's `@`
 * picker does, which the backend resolves against the thread's own worktree.
 *
 * **Which tree answered is part of the answer.** `root` is `"worktree"` when the thread
 * has one and `"project"` when it does not and the operator's own checkout stood in. The
 * distinction is load-bearing rather than informational: the change markers come from the
 * thread's branch, and painting them over the operator's checkout would be showing one
 * tree's edits on another tree's files.
 *
 * Neither call creates a worktree — the backend is explicit about that, because acquiring
 * a project's single checkout as a side effect of browsing would take it from whatever
 * holds it.
 */

import { api } from "~/lib/api";

/** Which filesystem answered a listing. */
export type WorktreeRoot = "worktree" | "project";

export interface WorktreeListing {
  root: WorktreeRoot;
  /** Repo-root-relative posix paths, ranked by the backend. */
  paths: string[];
  /** The scan hit its ceiling. Said out loud rather than implying the tree is this
   *  small — the panel prints it rather than quietly showing a partial tree. */
  truncated: boolean;
}

interface FilesDTO {
  root: WorktreeRoot;
  entries: { path: string; name: string }[];
  truncated: boolean;
}

/** The highest number of entries the backend will return; asking for more is capped
 *  there rather than refused, so the ceiling is stated here to be asked for explicitly. */
const LISTING_LIMIT = 500;

export async function fetchWorktreeFiles(
  projectId: string,
  conversationId: string,
): Promise<WorktreeListing> {
  const query = new URLSearchParams({
    conversation_id: conversationId,
    limit: String(LISTING_LIMIT),
  });
  const dto = await api.get<FilesDTO>(`/projects/${projectId}/files?${query}`);
  return {
    root: dto.root,
    paths: dto.entries.map((e) => e.path),
    truncated: dto.truncated,
  };
}

/** The path a worktree file's bytes are served from — handed to the panel's download
 *  slot, which fetches the blob itself. */
export function worktreeFilePath(
  projectId: string,
  conversationId: string,
  path: string,
): string {
  const query = new URLSearchParams({
    conversation_id: conversationId,
    path,
  });
  return `/projects/${projectId}/file?${query}`;
}

/** One file's text. The backend caps what it will send and reports the cut in a header,
 *  so a viewer showing the first two megabytes of a file can say so instead of looking
 *  like a viewer showing the file. */
export async function fetchWorktreeFileText(
  projectId: string,
  conversationId: string,
  path: string,
): Promise<{ text: string; truncated: boolean }> {
  const res = await api.getResponse(
    worktreeFilePath(projectId, conversationId, path),
  );
  return {
    text: await res.text(),
    truncated: res.headers.get("x-content-truncated") === "true",
  };
}
