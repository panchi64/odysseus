import { createSignal, type JSX } from "solid-js";
import { Checkbox } from "~/ui";
import { commandScopeLabel } from "../commandScope";
import type { ApprovalDecision } from "../model";

/** Shared opt-in state for "auto-approve this for the rest of the conversation",
 *  used by every approval surface so the signal, the scope mapping, and (via the
 *  toggle below) the label live in one place rather than being re-implemented per card.
 *
 *  Keyed by the **grant's scope** (`grantKey`), not by tool alone, because that is the
 *  shape the backend records: two deferred calls asking for the same act share one opt-in
 *  and produce one grant, while two different commands on the same tool are two of each.
 *  Keying by tool alone — which is what the backend grant used to be — would put one
 *  checkbox under two different labels, and a tick under one command would record a
 *  standing yes to the other. That is also why a command this file cannot name keys on the
 *  call rather than collapsing back onto the tool.
 *  The grant's real lifetime is backend-owned (operator-configurable
 *  `approval_grant_ttl_s`); this opt-in only requests one and never displays the TTL. */
export function createGrantToggle() {
  const [allowed, setAllowed] = createSignal<Record<string, boolean>>({});
  const set = (key: string, allow: boolean) =>
    setAllowed((a) => ({ ...a, [key]: allow }));
  const isAllowed = (key: string) => !!allowed()[key];
  // Scope is "conversation" only when the call is both approved and opted-in; the
  // backend ignores scope on a denial, but mapping it here keeps the payload honest.
  // *What* the conversation grant covers is the backend's to derive from the parked
  // call — this only asks for one.
  const scope = (key: string, approved: boolean): ApprovalDecision["scope"] =>
    approved && isAllowed(key) ? "conversation" : "once";
  return { isAllowed, set, scope };
}

/** The opt-in grant control itself — one canonical label and shape for both the
 *  generic approval card and the host-command terminal.
 *
 *  The label says what a grant *is* — a standing yes to this tool for this thread —
 *  and deliberately not what will happen because of it. What a grant buys depends on
 *  the thread's permission level, which is the backend's to decide and can change
 *  between the moment this is ticked and the next call: at Manual and Edit it settles
 *  the call outright, while at Auto it feeds the review as the operator's
 *  authorization and an unrecoverable act still comes back to be asked about. The old
 *  copy ("Allow for the rest of this conversation") promised the first of those at
 *  every level, which is a promise the chassis breaks at the one that is becoming the
 *  default.
 *
 *  It also says *what*, and the three answers are genuinely different. Where the call runs
 *  a command this file can name, the label names it — the grant is scoped to that act and
 *  not to the tool. Where it runs a command that **cannot** be named here (the reading is
 *  deliberately conservative — see `commandScope.ts`), the label says "this command": the
 *  backend scopes the grant to the command it reads, so "this tool" would state a wider
 *  standing yes than the one being given. Only a call that runs no command at all is a
 *  whole-tool grant, and only that one says so.
 *
 *  **Nothing here promises the grant exists.** The backend refuses to record one for a
 *  command no scope could stand for — one its own walk cannot read, or one reaching
 *  outside the worktree — and a guess made here would be a second, disagreeing answer to a
 *  question only it can settle. So the refusal is reported where it becomes a fact: the
 *  approve response names the calls it could not scope and `stream/approvals.ts` says so,
 *  rather than this label hedging on every command it happens not to recognise. */
export function ConversationGrantToggle(props: {
  /** The command line this approval would run, when it runs one. */
  command?: string;
  checked?: boolean;
  disabled?: boolean;
  onChange: (allow: boolean) => void;
}): JSX.Element {
  const label = () => {
    const scope = commandScopeLabel(props.command);
    if (scope) return `Don't ask again for \`${scope}\` in this conversation`;
    if (props.command)
      return "Don't ask again for this command in this conversation";
    return "Don't ask again for this tool in this conversation";
  };
  return (
    <Checkbox
      label={label()}
      checked={props.checked}
      disabled={props.disabled}
      onChange={props.onChange}
    />
  );
}
