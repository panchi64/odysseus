import type { IconName } from "~/ui";

/**
 * What kind of work a thread is — the backend's `services/modes.py` vocabulary, sent
 * verbatim on the send that creates the conversation and never translated on the way.
 *
 * **It lives in `lib/` rather than in `features/chat/` because two layers outside chat
 * need it.** The theme layer binds the signature accent to it (`ui/theme/accents.ts`),
 * and the app shell stamps it on the document root. A type owned by a feature and
 * imported by the design system would be a dependency pointing the wrong way, and
 * declaring the union twice would be worse: the two copies would drift the first time a
 * fourth mode arrives, and nothing would fail.
 *
 * `normal` and `research` work in the conversation's own sandbox container; `code` works
 * in a git worktree of a project's repository on the operator's machine.
 */
export type SessionMode = "normal" | "research" | "code";

export interface SessionModeSpec {
  id: SessionMode;
  /** Sentence case — the interface naming the thing to the operator. */
  label: string;
  /** What the mode changes, said in one line: the workspace and the tools. */
  description: string;
  icon: IconName;
}

/** The three, in the order the rail lists them. Ordinary work first — it is what most
 *  threads are, and a switch whose default sits in the middle reads as a spectrum. */
export const SESSION_MODES: readonly SessionModeSpec[] = [
  {
    id: "normal",
    label: "Normal",
    description: "General work in this thread's own sandbox.",
    icon: "chat",
  },
  {
    id: "research",
    label: "Research",
    description: "Reading the web and the corpus, with sources cited.",
    icon: "research",
  },
  {
    id: "code",
    label: "Code",
    description: "A git worktree of a directory on this machine.",
    icon: "code",
  },
];

export const SESSION_MODE_IDS: readonly SessionMode[] = SESSION_MODES.map(
  (spec) => spec.id,
);

/** The mode a thread is when nothing says otherwise — matching the backend's
 *  `DEFAULT_MODE`, and the one that reaches the least. */
export const DEFAULT_SESSION_MODE: SessionMode = "normal";

export function isSessionMode(value: string): value is SessionMode {
  return (SESSION_MODE_IDS as readonly string[]).includes(value);
}

/** Whatever the wire said, as a mode this build has a rule for. A row written by
 *  another build degrades to the mode that reaches the least rather than to a section
 *  of the rail the operator cannot open. */
export function sessionMode(value: string | undefined): SessionMode {
  return value && isSessionMode(value) ? value : DEFAULT_SESSION_MODE;
}

export function sessionModeSpec(mode: SessionMode): SessionModeSpec {
  return SESSION_MODES.find((spec) => spec.id === mode) ?? SESSION_MODES[0];
}
