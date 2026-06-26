import { createSignal, type JSX } from "solid-js";
import { Checkbox } from "~/ui";
import type { ApprovalDecision } from "../model";

/** Shared opt-in state for "auto-approve this tool for the rest of the conversation",
 *  used by every approval surface so the signal, the scope mapping, and (via the
 *  toggle below) the label live in one place rather than being re-implemented per card.
 *
 *  Keyed by **tool name**, not tool-call id, because the backend grant is per-tool
 *  (owner, conversation, tool): two deferred calls to the same tool in one batch share
 *  one opt-in, so the checkboxes stay consistent and a single grant is recorded. The
 *  grant's real lifetime is backend-owned (operator-configurable `approval_grant_ttl_s`);
 *  this opt-in only requests one and never re-derives or displays the TTL. */
export function createGrantToggle() {
  const [allowed, setAllowed] = createSignal<Record<string, boolean>>({});
  const set = (toolName: string, allow: boolean) =>
    setAllowed((a) => ({ ...a, [toolName]: allow }));
  const isAllowed = (toolName: string) => !!allowed()[toolName];
  // Scope is "conversation" only when the call is both approved and opted-in; the
  // backend ignores scope on a denial, but mapping it here keeps the payload honest.
  const scope = (
    toolName: string,
    approved: boolean,
  ): ApprovalDecision["scope"] =>
    approved && isAllowed(toolName) ? "conversation" : "once";
  return { isAllowed, set, scope };
}

/** The opt-in grant control itself — one canonical label and shape for both the
 *  generic approval card and the host-command terminal. */
export function ConversationGrantToggle(props: {
  checked?: boolean;
  disabled?: boolean;
  onChange: (allow: boolean) => void;
}): JSX.Element {
  return (
    <Checkbox
      label="Allow for the rest of this conversation"
      checked={props.checked}
      disabled={props.disabled}
      onChange={props.onChange}
    />
  );
}
