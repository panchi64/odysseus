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

import { api, isApiError } from "~/lib/api";

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

/** What the viewer needs to render one file — or to say why it cannot. */
export interface WorktreeFileText {
  text: string;
  /** The backend cut the file at its ceiling and said so in a header, so a viewer
   *  showing the first part of a file can say so instead of looking like a viewer
   *  showing the file. */
  truncated: boolean;
  /** The listing offers it and the read route refuses it. **This resolves rather than
   *  rejecting**, because it is an ordinary outcome rather than a failure: the two
   *  disagree by design. `list_files` reports what git reports, and the read goes
   *  through the containment check — so a symlink pointing out of the tree is listed
   *  and is never opened. Rejecting left the pane on its loading state forever, which
   *  told the operator nothing and looked like a hang. */
  unreadable: boolean;
}

export async function fetchWorktreeFileText(
  projectId: string,
  conversationId: string,
  path: string,
): Promise<WorktreeFileText> {
  try {
    const res = await api.getResponse(
      worktreeFilePath(projectId, conversationId, path),
    );
    return {
      text: await res.text(),
      truncated: res.headers.get("x-content-truncated") === "true",
      unreadable: false,
    };
  } catch (err) {
    // Only the refusal. Anything else is a genuine failure and belongs in the
    // resource's error arm, where it gets a retry rather than a sentence.
    if (isApiError(err) && err.status === 404)
      return { text: "", truncated: false, unreadable: true };
    throw err;
  }
}
