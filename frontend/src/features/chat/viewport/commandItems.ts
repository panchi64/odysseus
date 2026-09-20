/**
 * Every command a thread has run, in the order it ran them.
 *
 * Derived from the transcript's own terminal blocks rather than fetched: the fold and
 * the cold read both already produce a `HostCommand` per call, so a second source would
 * be a second answer to "what did this thread run" — and the one that disagreed would
 * be this one, since it would not see a command that is still streaming.
 *
 * Presentation-only, and therefore automatically thread-scoped, exactly like
 * `collectViewItems` beside it.
 */

import type { ChatMessage, HostCommand } from "../model";

/** Chronological, oldest first — the transcript's own order.
 *
 *  Deliberately not ranked by outcome. A command log is read as a sequence (this ran,
 *  then that failed, then this fixed it), and floating the failures to the top breaks
 *  the one relationship between the rows that carries meaning. What failure earns
 *  instead is being **open** by default, which costs the ordering nothing. */
export function collectCommands(messages: ChatMessage[]): HostCommand[] {
  const commands: HostCommand[] = [];
  for (const m of messages)
    for (const b of m.blocks ?? [])
      if (b.kind === "host_command") commands.push(b.command);
  return commands;
}

/** How many of them went wrong — the panel header's readout.
 *
 *  `denied` counts: from this surface's point of view the question is "did this thread
 *  get what it asked for", and a command that was refused did not run any more than one
 *  that exited non-zero did. */
export function failedCount(commands: HostCommand[]): number {
  return commands.filter((c) => c.phase === "error" || c.phase === "denied")
    .length;
}
