/** Slash-command data contracts.
 *
 *  A command is a name the operator types to reach something the platform already has —
 *  a published skill, a sub-agent, a thread action. **Every rule about them is the
 *  backend's**: which exist, which this thread may use, which wins a shared name, and
 *  what the headings are called. These types only describe what comes back.
 */

/** What picking a command does. `prompt` composes a turn; `action` sends no message. */
export type CommandKind = "prompt" | "action";

/** The thread actions a command can name. A **stable id**, never a route: the room maps
 *  it onto a relay it already owns, and `new-thread` has no route behind it at all.
 *  An id this build does not know is rendered disabled rather than guessed at, which is
 *  what lets the backend add one without waiting for the client. */
export type CommandActionId =
  "compact" | "fork" | "new-thread" | "permission-level" | "retitle";

export interface CommandActionArgument {
  required: boolean;
  /** A closed set to offer, or empty for free text. */
  choices: string[];
}

export interface Command {
  /** What the operator types after the slash. */
  name: string;
  /** The name that resolves to *this* command and no other (`skill:reviewer`) — what
   *  gets sent when the bare name is ambiguous. */
  qualifiedName: string;
  /** Which source answered; the picker's grouping key. */
  group: string;
  title: string;
  description: string;
  argumentHint: string | null;
  kind: CommandKind;
  actionId: CommandActionId | null;
  actionArgument: CommandActionArgument | null;
  /** The qualified name that wins this command's bare name, when another source
   *  outranks it. Both rows still arrive — two things sharing a name is something the
   *  operator gets to see rather than have resolved silently. */
  shadowedBy: string | null;
}

/** A picker heading. Supplied by the backend so a source added there is never a blank
 *  section in a client that has not shipped yet. */
export interface CommandGroup {
  id: string;
  label: string;
  order: number;
}

export interface CommandCatalog {
  groups: CommandGroup[];
  commands: Command[];
}

/** What rides `POST /chat` when a turn was started from a command. The prompt beside it
 *  is still the operator's literal `/name …` — this says which command that token was,
 *  so the backend can resolve and expand it. */
export interface CommandInvocation {
  name: string;
  argument: string;
}
