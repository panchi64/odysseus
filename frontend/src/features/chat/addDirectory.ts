/**
 * Pointing the rail at a directory on the operator's machine.
 *
 * This is the whole of how code work begins now, so it lives on its own rather than
 * inside whichever control happens to call it: the rail's header button calls it, the
 * empty state's button calls it, and the keyboard path reaches it by focusing the first
 * of those. Three callers of one act, which is what it was already — it was simply
 * buried in a line under the mode switch, where the directory came *second*.
 *
 * Any directory does. Projects are still the storage and the git machinery, but they are
 * not paperwork the operator files before they can start: the native chooser hands back
 * a host path, and the backend files it on first use, idempotently by the path itself.
 */

import { createSignal, type Accessor } from "solid-js";
import { toast } from "~/ui";
import { usePathPicker } from "~/lib/hostPicker";
import { pathLabel } from "~/lib/format";
import { ensureProjectForPath, type Project } from "~/lib/stores/projects";
import { setCodeProjectId } from "~/lib/stores/sessionMode";

/** What to call a directory, wherever it is named.
 *
 *  The rail's heading and the chat header's subtitle must agree — they are two views of
 *  one staged thread, and a directory called one thing in the rail and another above the
 *  composer is exactly the ambiguity `parent/name` was added to remove. So the rule is
 *  written once: the operator's own name for the project when they have renamed it away
 *  from the directory's, and otherwise `parent/name`, which is the smallest thing that
 *  tells two directories both called `frontend` apart. */
export function directoryLabel(project: Project): string {
  const { parent, name } = pathLabel(project.rootPath);
  return project.name === name && parent ? `${parent}/${name}` : project.name;
}

export interface AddDirectory {
  /** Open the chooser, file what comes back, and stage it for the next code thread.
   *  Resolves to null when the operator cancelled, when this host has no chooser, or
   *  when the backend refused the path. */
  add: () => Promise<Project | null>;
  busy: Accessor<boolean>;
}

export function useAddDirectory(): AddDirectory {
  const picker = usePathPicker();
  const [busy, setBusy] = createSignal(false);

  const add = async (): Promise<Project | null> => {
    // Guarded here rather than by each caller disabling its own control: `busy` is
    // offered for the paint, but two choosers open from one double-click would both
    // resolve, and the second would overwrite the directory the operator picked first.
    if (busy()) return null;
    const pick = picker();
    if (!pick) {
      // No native chooser on this host. The projects section still takes a typed path,
      // so say where to go rather than leaving a dead button.
      toast.error(
        "No folder chooser on this host — add the directory under projects",
      );
      return null;
    }
    setBusy(true);
    try {
      const path = await pick({
        mode: "directory",
        title: "Choose a directory",
      });
      if (!path) return null;
      const project = await ensureProjectForPath(path);
      setCodeProjectId(project.id);
      // Said once, here, rather than discovered halfway through a session: a worktree
      // is cut from the project's base ref, so work the operator has not committed in
      // their own checkout is invisible to the agent. The rail's heading carries the
      // same two facts as a marker, since a toast is gone in seconds and this is a
      // property of the directory rather than of the moment it was added.
      if (!project.repo.isGitRepo)
        toast.error(
          `${project.name} isn't a git repository yet — create one under projects first`,
        );
      else if ((project.repo.uncommittedChanges ?? 0) > 0)
        toast.info(
          `${project.repo.uncommittedChanges} uncommitted change${
            project.repo.uncommittedChanges === 1 ? "" : "s"
          } in ${project.name} won't be visible to the agent`,
        );
      return project;
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Couldn't open that directory",
      );
      return null;
    } finally {
      setBusy(false);
    }
  };

  return { add, busy };
}

/* ── Reaching the button from the keyboard ────────────────────────────────────
   `mod+shift+o` means "start a thread", and in a worktree mode with no directory
   there is nothing yet to start one *in*. It could raise the chooser itself, but a
   modal OS dialog from a reflex keystroke is the wrong answer — the operator hit a
   key without looking. So it moves focus to the rail's button and stops: the next
   Enter opens the chooser, and it was asked for.

   A module-level seam because the two live in different components — the rail owns the
   button, the chat room owns the keymap — and this mirrors the module-level handoffs
   the viewport already uses for exactly that shape. */

let addButton: HTMLButtonElement | undefined;

/** The rail's ADD DIRECTORY button, as a `ref` callback. */
export function registerAddDirectoryButton(el: HTMLButtonElement): void {
  addButton = el;
}

/** Put the operator in front of the chooser without opening it. Returns whether
 *  there was a button to focus — false on a surface where the rail isn't mounted. */
export function focusAddDirectory(): boolean {
  // `isConnected`, not merely non-undefined: Solid does not call a `ref` with null on
  // cleanup, so this can still hold a button that has left the document. Focusing a
  // detached node silently does nothing, and returning true for it would tell the
  // caller the operator had been handed off when nothing happened at all.
  if (!addButton?.isConnected) return false;
  addButton.focus();
  return true;
}
