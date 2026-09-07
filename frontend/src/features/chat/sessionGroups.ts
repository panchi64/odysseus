import { sessionModeSpec, type SessionMode } from "~/lib/modes";
import type { ChatSummary } from "./model";

/**
 * How the rail arranges a mode's threads.
 *
 * The three modes do not want the same list. Normal and Research threads have
 * nothing to be filed under — they work in their own sandbox, so the only useful
 * order is the one they already have, recency with pins on top. A Code thread
 * has a directory, and after a fortnight of them the flat list is a hundred rows
 * whose titles all sound alike; what the operator is actually looking for is
 * "the threads in *this* repository", which is a heading, not a search.
 *
 * So this is a strategy over one input rather than two list components. Pure:
 * ordering is done by the caller (it reads the pin store) and this only decides
 * where the divisions fall, which is what makes it testable without a DOM.
 */

/** The heading a code thread lands under when its project is gone — deleting a
 *  project unfiles its conversations rather than deleting them, so this run is
 *  real and has to be reachable. Matches the projects vocabulary, where *unfiled*
 *  means visible everywhere rather than orphaned. */
export const UNFILED_GROUP = "Unfiled";

/** One directory the operator works in, as the rail needs it: the project it is, and
 *  what to call it. The caller resolves the name (`pathLabel`) — this file decides
 *  where divisions fall and nothing about how they read. */
export interface WorkspaceDirectory {
  id: string;
  label: string;
}

export interface SessionGroup {
  /** Stable identity for keying and for remembering which sections are open. */
  id: string;
  /** The heading, or null for a run that is simply the whole list — which is
   *  what Normal and Research get. A null label is the signal not to draw a
   *  section header at all, rather than a header with nothing to say. */
  label: string | null;
  /** The project behind the heading, or null for `Unfiled`. What the section's own
   *  controls act on — starting a thread here, archiving the directory — none of which
   *  `Unfiled` has, because there is no directory behind it. */
  projectId: string | null;
  sessions: ChatSummary[];
}

/**
 * Partition an **already ordered** list into the sections this mode shows.
 *
 * Groups that hold threads appear in the order their first thread does, so the input's
 * ordering carries all the way through: a pinned thread floats its whole workspace to
 * the top, and otherwise the most recently touched repository leads. That is one rule
 * rather than two, and it means the rail never reorders itself for a reason the
 * operator cannot see in the rows.
 *
 * `directories` is what the operator works in, whether or not any of it has been worked
 * on yet — the directory now comes *first* and the thread is started from it, so a
 * directory with no threads is the normal beginning of a piece of work rather than an
 * empty row. Those trail the ones holding threads, in the order given (the projects
 * listing, already most-recently-opened first): a section with nothing in it has
 * nothing to say about how recently the operator was there.
 *
 * Filing is by **project id**, not by name. Two directories can be called `frontend`,
 * and filing by name would merge two repositories into one section whose controls would
 * then act on whichever won.
 */
export function groupSessions(
  sessions: ChatSummary[],
  mode: SessionMode,
  directories: readonly WorkspaceDirectory[] = [],
): SessionGroup[] {
  // The heading is the workspace, so only a mode that *has* one gets sections.
  if (sessionModeSpec(mode).workspace !== "worktree")
    return sessions.length
      ? [{ id: mode, label: null, projectId: null, sessions }]
      : [];

  const named = new Map(directories.map((d) => [d.id, d.label]));
  const groups: SessionGroup[] = [];
  const byId = new Map<string, SessionGroup>();

  const section = (id: string, label: string, projectId: string | null) => {
    let group = byId.get(id);
    if (!group) {
      group = { id, label, projectId, sessions: [] };
      byId.set(id, group);
      groups.push(group);
    }
    return group;
  };

  for (const s of sessions) {
    // Unfiled: the thread's project is gone (deleting one unfiles its conversations
    // rather than deleting them), so there is no directory to file it under.
    if (!s.projectId) {
      section(UNFILED_GROUP, UNFILED_GROUP, null).sessions.push(s);
      continue;
    }
    // A thread whose project *exists* but isn't among the directories is **left out**,
    // not swept into Unfiled. That is the archived case, and dropping it is the point:
    // archiving a directory is the operator saying they no longer work there, and a
    // rail that hid the heading while keeping ten of its threads loose in the list
    // would have honoured the letter of that and none of the intent. Nothing is lost —
    // pointing at the directory again un-archives it and the threads come back under
    // it. Callers must not render until the directory listing has resolved, or every
    // filed thread would vanish for the width of a fetch.
    const label = named.get(s.projectId);
    if (label !== undefined)
      section(s.projectId, label, s.projectId).sessions.push(s);
  }

  for (const d of directories) section(d.id, d.label, d.id);
  return groups;
}
