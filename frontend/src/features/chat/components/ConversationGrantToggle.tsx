import { Show, createSignal, type JSX } from "solid-js";
import { Checkbox, Segmented, Stack } from "~/ui";
import {
  commandScopeLabel,
  tickedWidth,
  type GrantWidth,
} from "../commandScope";
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
  const [allowed, setAllowed] = createSignal<Record<string, GrantWidth>>({});
  const set = (key: string, width: GrantWidth) =>
    setAllowed((a) => ({ ...a, [key]: width }));
  const widthOf = (key: string): GrantWidth => allowed()[key] ?? "off";
  const isAllowed = (key: string) => widthOf(key) !== "off";
  // A standing yes travels only when the call is both approved and opted-in; the backend
  // ignores scope on a denial, but mapping it here keeps the payload honest.
  //
  // The two widths are two wire values, and the narrower one still says nothing about
  // *what* it covers — that stays the backend's to derive from the parked call, because a
  // scope the client could name is a scope it could widen. The wider one names no scope
  // either: it names the tool, which the parked call already says.
  const scope = (key: string, approved: boolean): ApprovalDecision["scope"] => {
    if (!approved) return "once";
    switch (widthOf(key)) {
      case "tool":
        return "conversation_tool";
      case "command":
        return "conversation";
      default:
        return "once";
    }
  };
  return { isAllowed, widthOf, set, scope };
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
 *  ── The second width, and why it is a second control ──
 *  Scoping to the command is right and is not always what the operator means. Someone who
 *  has decided to stop reading a thread's shell prompts gets a fresh one per command, and
 *  under the old single tick had no way to say otherwise. So a checked opt-in on a
 *  command-running call reveals a two-way pick between that command and everything the
 *  tool runs — and the wider one is **a separate control, not a wider default**, because
 *  it is a materially larger thing to say and the narrow one has to stay the easy path.
 *  Its description says what it costs in the only terms that matter at the level that is
 *  the default: nothing this tool runs is asked about again, and an act nobody can undo
 *  still comes back.
 *
 *  Where no command is involved there is only one width, so no picker appears — a control
 *  offering the same choice twice invents a decision. **That single width is the wider
 *  one**, and it has to be: such a call has nothing narrower to be scoped to, the label
 *  above already says "this tool", and recording the narrower width there would leave the
 *  checkbox promising a standing yes that the level doing the deciding does not honour.
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
  /** The tool being approved — named in the wider option, so the operator reads what they
   *  are handing over rather than "this tool". */
  toolName?: string;
  width?: GrantWidth;
  disabled?: boolean;
  onChange: (width: GrantWidth) => void;
}): JSX.Element {
  const label = () => {
    const scope = commandScopeLabel(props.command);
    if (scope) return `Don't ask again for \`${scope}\` in this conversation`;
    if (props.command)
      return "Don't ask again for this command in this conversation";
    return "Don't ask again for this tool in this conversation";
  };
  // The narrower option is only a *different* thing to say where the call runs a command.
  // For anything else the tool is the act, the checkbox above already names it, and a
  // picker offering one choice twice would invent a decision nobody has to make.
  const hasWidths = () => !!props.command;
  const width = () => props.width ?? "off";
  return (
    <Stack gap={1}>
      <Checkbox
        label={label()}
        checked={width() !== "off"}
        disabled={props.disabled}
        onChange={(allow) =>
          props.onChange(allow ? tickedWidth(props.command) : "off")
        }
      />
      <Show when={hasWidths() && width() !== "off"}>
        <Segmented
          class="ml-6"
          fill={false}
          aria-label="What this standing approval covers"
          value={width() === "tool" ? "tool" : "command"}
          onChange={(next) => props.onChange(next as GrantWidth)}
          options={[
            {
              value: "command",
              label: "Just this command",
              description: "Any other command still pauses for approval.",
            },
            {
              value: "tool",
              label: props.toolName
                ? `Anything ${props.toolName} runs`
                : "Anything this tool runs",
              description:
                "Every command it runs for the rest of this conversation, without asking. Actions that can't be undone still pause.",
            },
          ]}
        />
      </Show>
    </Stack>
  );
}
