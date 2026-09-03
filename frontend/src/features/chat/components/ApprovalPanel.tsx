import { createSignal, For, Show, type JSX } from "solid-js";
import { Button, Row, Stack, StatusFlag, Text } from "~/ui";
import { grantKey } from "../commandScope";
import { formatArgs } from "../data";
import type { Approval, ApprovalDecision } from "../model";
import {
  ConversationGrantToggle,
  createGrantToggle,
} from "./ConversationGrantToggle";

/**
 * **The operator's decision point for sensitive actions the agent paused on.**
 *
 * It reports decisions upward rather than submitting them, because it is no longer the
 * whole of what a park can be waiting for: the same park may also hold questions, and the
 * run resumes on one body covering all of it. `ParkDock` owns the submit; this owns the
 * approve/deny state and the grant opt-in.
 *
 * Each approval also offers an opt-in "allow for the rest of this conversation" grant
 * (off by default): when checked and approved, the backend records a grant so the same
 * act auto-approves for the rest of the conversation instead of re-prompting. The grant's
 * scope is the backend's to derive from the parked call — for a tool that runs a command
 * it is that command, not the tool — and this only asks for one.
 */
export function ApprovalPanel(props: {
  approvals: Approval[];
  /** Collected upward on every change; complete only once every call is decided. */
  onChange: (decisions: ApprovalDecision[], allDecided: boolean) => void;
}): JSX.Element {
  const [decisions, setDecisions] = createSignal<Record<string, boolean>>({});
  const grant = createGrantToggle();

  // The command an approval would run, when it runs one. The grant it can opt into is
  // scoped to that act rather than to the tool, so it keys the opt-in and names it.
  const commandOf = (approval: Approval): string | undefined =>
    typeof approval.args.command === "string"
      ? approval.args.command
      : undefined;
  const keyOf = (approval: Approval) =>
    grantKey(approval.name, commandOf(approval), approval.toolCallId);

  const emit = () => {
    const decided = decisions();
    props.onChange(
      props.approvals
        .filter((a) => a.toolCallId in decided)
        .map((a) => ({
          tool_call_id: a.toolCallId,
          approved: decided[a.toolCallId],
          scope: grant.scope(keyOf(a), decided[a.toolCallId]),
        })),
      props.approvals.every((a) => a.toolCallId in decided),
    );
  };

  const decide = (toolCallId: string, approved: boolean) => {
    setDecisions((d) => ({ ...d, [toolCallId]: approved }));
    emit();
  };

  return (
    <Stack gap={3}>
      <For each={props.approvals}>
        {(approval) => {
          const decision = () => decisions()[approval.toolCallId];
          return (
            <Stack gap={2}>
              <Row gap={2} align="center">
                <StatusFlag status="warn" dot>
                  {approval.name}
                </StatusFlag>
                {/* The one thing a reviewer can say that changes how this decision should
                    be read. It used to refuse such a call outright, which kept the
                    operator out of the decision they most need to be in; now the call
                    arrives here, and the finding has to arrive with it. */}
                <Show when={approval.risk === "too_destructive"}>
                  <StatusFlag status="alert">Cannot be undone</StatusFlag>
                </Show>
                <Show when={approval.toolCallId in decisions()}>
                  <StatusFlag status={decision() ? "nominal" : "alert"}>
                    {decision() ? "Approved" : "Denied"}
                  </StatusFlag>
                </Show>
              </Row>
              <Text variant="body" tone="bright">
                {approval.summary}
              </Text>
              <Show when={approval.explanation}>
                <Text variant="micro" tone="dim">
                  {approval.explanation}
                </Text>
              </Show>
              <Show when={approval.risk === "too_destructive"}>
                <Text variant="micro" tone="warn">
                  {approval.reviewReason}
                </Text>
              </Show>
              <Show when={Object.keys(approval.args).length > 0}>
                <Text variant="micro" tone="dim" class="break-words">
                  {formatArgs(approval.args)}
                </Text>
              </Show>
              <Row gap={2}>
                <Button
                  variant="primary"
                  size="sm"
                  leading="check"
                  onClick={() => decide(approval.toolCallId, true)}
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  leading="close"
                  onClick={() => decide(approval.toolCallId, false)}
                >
                  Deny
                </Button>
              </Row>
              <ConversationGrantToggle
                command={commandOf(approval)}
                checked={grant.isAllowed(keyOf(approval))}
                onChange={(v) => {
                  grant.set(keyOf(approval), v);
                  emit();
                }}
              />
            </Stack>
          );
        }}
      </For>
    </Stack>
  );
}
