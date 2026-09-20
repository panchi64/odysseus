/**
 * Flat paths, read as the tree they describe.
 *
 * A listing is a list of posix paths; a reader looking for `src/features/chat/model.ts`
 * among four hundred of them is reading directory names over and over. Grouping them is
 * **presentation** — the same kind of derivation the diff surface does when it draws its
 * own separators — and it decides nothing: no row's meaning changes, only where it sits
 * and how much of its path it has to repeat.
 *
 * Pure, and tested as such. Nothing here fetches, and nothing here classifies a file.
 */

/** One rendered line: either a directory heading or a file under it. */
export type FileTreeRow =
  | { kind: "dir"; key: string; depth: number; name: string }
  | {
      kind: "file";
      key: string;
      depth: number;
      /** What the row prints — the basename under a heading, the whole path when flat. */
      label: string;
      /** The full repo-root-relative path, which is the row's identity. */
      path: string;
    };

/** The directory part of a posix path, or `""` for a file at the root. */
function dirOf(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? "" : path.slice(0, cut);
}

function baseOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/**
 * Group `paths` under their directories, in the order the paths arrive.
 *
 * **Order is preserved, never re-sorted.** The backend ranks a listing and the diff ranks
 * its files; re-ordering either here would be the client overruling a verdict it was
 * handed. A directory takes the position of the first path that mentions it, and its
 * files follow in their own original order.
 *
 * A directory heading is emitted once per *distinct* directory, with its full relative
 * path as the name rather than one heading per path segment — a tree of nested chevrons
 * costs a reader more than the repetition it saves at this size.
 */
export function groupByDirectory(paths: string[]): FileTreeRow[] {
  const rows: FileTreeRow[] = [];
  let current: string | null = null;
  for (const path of paths) {
    const dir = dirOf(path);
    if (dir !== current) {
      current = dir;
      // A file at the repository root has no heading to sit under — inventing one
      // ("/" or "root") would name a directory the operator never sees in a path.
      if (dir !== "")
        rows.push({ kind: "dir", key: `dir:${dir}`, depth: 0, name: dir });
    }
    rows.push({
      kind: "file",
      key: path,
      depth: dir === "" ? 0 : 1,
      label: dir === "" ? path : baseOf(path),
      path,
    });
  }
  return rows;
}
