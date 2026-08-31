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

export interface SessionGroup {
  /** Stable identity for keying and for remembering which sections are open. */
  id: string;
  /** The heading, or null for a run that is simply the whole list — which is
   *  what Normal and Research get. A null label is the signal not to draw a
   *  section header at all, rather than a header with nothing to say. */
  label: string | null;
  sessions: ChatSummary[];
}

/**
 * Partition an **already ordered** list into the sections this mode shows.
 *
 * Groups appear in the order their first thread does, so the input's ordering
 * carries all the way through: a pinned thread floats its whole workspace to the
 * top, and otherwise the most recently touched repository leads. That is one
 * rule rather than two, and it means the rail never reorders itself for a reason
 * the operator cannot see in the rows.
 */
export function groupSessions(
  sessions: ChatSummary[],
  mode: SessionMode,
): SessionGroup[] {
  // The heading is the workspace, so only a mode that *has* one gets sections.
  if (sessionModeSpec(mode).workspace !== "worktree")
    return sessions.length ? [{ id: mode, label: null, sessions }] : [];

  const groups: SessionGroup[] = [];
  const byLabel = new Map<string, SessionGroup>();
  for (const session of sessions) {
    const label = session.workspace || UNFILED_GROUP;
    let group = byLabel.get(label);
    if (!group) {
      group = { id: label, label, sessions: [] };
      byLabel.set(label, group);
      groups.push(group);
    }
    group.sessions.push(session);
  }
  return groups;
}
