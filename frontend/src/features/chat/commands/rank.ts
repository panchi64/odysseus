/**
 * Matching a typed `/query` against the catalog — the one presentation rule left after
 * the backend has decided everything else.
 *
 * Ranked in **exclusive buckets**, the same discipline `app/nav/settings-search.ts`
 * keeps and for the same reason: a name-prefix match has to beat a description that
 * merely mentions the word, or typing a command's own name surfaces some other row
 * first. A command is counted once, by its strongest field.
 *
 * Takes its rows as an argument rather than reaching the seam, so the rule can be
 * exercised against a fixture instead of against whatever the backend happens to hold.
 */

import type { Command, CommandGroup } from "./model";

/** Commands matching `query`, best first. An empty query is the whole catalog — the
 *  menu opens on the bare trigger and doubles as a directory of what exists. */
export function rankCommands(query: string, commands: Command[]): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  const byPrefix: Command[] = [];
  const byName: Command[] = [];
  const byTitle: Command[] = [];
  const byDescription: Command[] = [];
  for (const command of commands) {
    const name = command.name.toLowerCase();
    if (name.startsWith(q)) byPrefix.push(command);
    else if (name.includes(q)) byName.push(command);
    else if (command.title.toLowerCase().includes(q)) byTitle.push(command);
    else if (command.description.toLowerCase().includes(q))
      byDescription.push(command);
  }
  return [...byPrefix, ...byName, ...byTitle, ...byDescription];
}

export interface RankedGroup {
  id: string;
  label: string;
  commands: Command[];
}

/** The ranked commands, back under their headings.
 *
 *  Groups keep the backend's declared order rather than following the ranking, because
 *  a heading that jumps around as the operator types is harder to read than a stable
 *  one — the ranking's job is which *rows* survive and in what order within a section.
 *  A group with nothing left in it is dropped.
 */
export function groupCommands(
  commands: Command[],
  groups: CommandGroup[],
): RankedGroup[] {
  return [...groups]
    .sort((a, b) => a.order - b.order)
    .map((group) => ({
      id: group.id,
      label: group.label,
      commands: commands.filter((command) => command.group === group.id),
    }))
    .filter((group) => group.commands.length > 0);
}

/** The name this command is invoked by — in the field *and* on the wire.
 *
 *  The **qualified** name whenever another source outranks this one, so picking the
 *  shadowed `reviewer` reaches the one that was shown rather than the one that won the
 *  bare name. One string for both halves rather than a pretty name in the field and a
 *  precise one on the wire: the operator's literal text is the turn of record, and a
 *  transcript reading `/reviewer` when a different `reviewer` ran is a message that
 *  quietly misreports what happened. `/agent:reviewer` is a little more machinery in
 *  their words, and it is the accurate amount.
 */
export function invocationName(command: Command): string {
  return command.shadowedBy ? command.qualifiedName : command.name;
}
