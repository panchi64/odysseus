/**
 * Binding the `@` menu to the room.
 *
 * Simpler than its `/` counterpart, because there is only one kind of row: picking a file
 * completes the token and stages a reference that rides the next send. Nothing acts.
 *
 * **Only where there is a filesystem to browse.** A sandbox thread works in a container
 * with nothing in it the operator has ever seen, so `@` means nothing there and the menu
 * stays shut rather than opening empty.
 */

import { createSignal } from "solid-js";
import type {
  ComposerMenuGroup,
  ComposerMenuItem,
  ComposerTrigger,
} from "~/ui";
import { sessionModeSpec, type SessionMode } from "~/lib/modes";
import { settled } from "~/lib/resource";
import { useProjectFiles } from "./data";

export interface ComposerFileRefs {
  groups: () => ComposerMenuGroup[];
  onQuery: (token: { trigger: ComposerTrigger; query: string } | null) => void;
  /** The path to complete the token with, or null when the row is unknown. */
  onPick: (item: ComposerMenuItem) => string | null;
  /** The references still named by `text`, for the send. Clears the staging. */
  consume: (text: string) => string[];
  clear: () => void;
}

/** Row id: the path, which is unique within a listing by construction. */
const rowId = (path: string): string => `file-${path}`;

export function createComposerFileRefs(
  mode: () => SessionMode,
  projectId: () => string | null,
  conversationId: () => string | null,
): ComposerFileRefs {
  const [query, setQuery] = createSignal<string | null>(null);
  const [staged, setStaged] = createSignal<string[]>([]);
  const files = useProjectFiles(projectId, conversationId, query);

  const rooted = () => sessionModeSpec(mode()).workspace === "worktree";

  const groups = (): ComposerMenuGroup[] => {
    // `settled`, not a bare `.latest`: the menu opens on a keystroke and must not suspend
    // the room behind it while the listing is in flight. `latest` alone is not that read —
    // on an *unresolved* resource it calls through, which inside this tracked scope
    // registers with the nearest `Suspense` and takes the panel off screen rather than
    // rendering it. `settled` guards on `state` first, so a fetch in flight reads
    // `undefined` and the menu simply stays shut until the rows arrive.
    const listing = settled(files);
    if (query() === null || !listing || listing.entries.length === 0) return [];
    return [
      {
        id: "files",
        // The label says which tree answered, because the two genuinely differ: a
        // worktree is cut from the project's base ref, so the operator's uncommitted
        // work is in one and not the other.
        label: listing.root === "worktree" ? "Files in this branch" : "Files",
        items: listing.entries.map((file): ComposerMenuItem => ({
          id: rowId(file.path),
          label: file.name,
          // The path under the name, not instead of it: the operator is looking for a
          // file and then checking which one, in that order.
          detail: file.path,
        })),
      },
    ];
  };

  return {
    groups,
    onQuery: (token) => {
      // `/` is the command menu's trigger, not this one's; and a sandbox thread has no
      // filesystem the operator has ever seen. Reporting null rather than ignoring keeps
      // one menu open at a time.
      setQuery(token?.trigger === "@" && rooted() ? token.query : null);
    },
    onPick: (item) => {
      const path = settled(files)?.entries.find(
        (file) => rowId(file.path) === item.id,
      )?.path;
      if (!path) return null;
      setStaged((current) =>
        current.includes(path) ? current : [...current, path],
      );
      return path;
    },
    consume: (text) => {
      const all = staged();
      setStaged([]);
      // The **text is the turn of record**, so a reference only counts while the message
      // still names it — the operator may have picked a file and then deleted the token.
      return all.filter((path) => text.includes(`@${path}`));
    },
    clear: () => setStaged([]),
  };
}
