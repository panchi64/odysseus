import { createSignal, For, Show, type JSX } from "solid-js";
import { Button, Row, Stack, StatusFlag, Text } from "~/ui";
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
 * approve/deny state and the per-tool grant opt-in.
 *
 * Each approval also offers an opt-in "allow for the rest of this conversation" grant
 * (off by default): when checked and approved, the backend records a grant so that tool
 * auto-approves for the rest of the conversation instead of re-prompting.
 */
export function ApprovalPanel(props: {
  approvals: Approval[];
  /** Collected upward on every change; complete only once every call is decided. */
  onChange: (decisions: ApprovalDecision[], allDecided: boolean) => void;
}): JSX.Element {
  const [decisions, setDecisions] = createSignal<Record<string, boolean>>({});
  const grant = createGrantToggle();

  const emit = () => {
    const decided = decisions();
    props.onChange(
      props.approvals
        .filter((a) => a.toolCallId in decided)
        .map((a) => ({
          tool_call_id: a.toolCallId,
          approved: decided[a.toolCallId],
          scope: grant.scope(a.name, decided[a.toolCallId]),
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
                checked={grant.isAllowed(approval.name)}
                onChange={(v) => {
                  grant.set(approval.name, v);
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
