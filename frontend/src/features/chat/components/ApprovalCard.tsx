import { createSignal, For, Show, type JSX } from "solid-js";
import { Button, Panel, Row, Stack, StatusFlag, Text } from "~/ui";
import { formatArgs } from "../data";
import type { Approval, ApprovalDecision } from "../model";
import {
  ConversationGrantToggle,
  createGrantToggle,
} from "./ConversationGrantToggle";

/**
 * The operator's decision point for sensitive actions the agent paused on. The
 * backend requires a single response covering *every* pending call, so we collect
 * an approve/deny per approval and submit them together once all are decided. The
 * run resumes on the same open stream — no reload.
 *
 * Each approval also offers an opt-in "allow for the rest of this conversation"
 * grant (off by default): when checked and approved, the backend records a grant so
 * that tool auto-approves for the rest of the conversation instead of re-prompting.
 */
export function ApprovalCard(props: {
  approvals: Approval[];
  onSubmit: (decisions: ApprovalDecision[]) => void | Promise<void>;
}): JSX.Element {
  const [decisions, setDecisions] = createSignal<Record<string, boolean>>({});
  const grant = createGrantToggle();
  const [submitting, setSubmitting] = createSignal(false);
  // Set together (the whole batch resumes on one decision, so a 409 stales all of
  // them at once) once a submitted decision for this card 409'd — the run already
  // resumed elsewhere. Non-interactive from then on; a refetch reconciles the
  // transcript with whatever actually happened.
  const stale = () => props.approvals.some((a) => a.stale);

  const decide = (toolCallId: string, approved: boolean) =>
    setDecisions((d) => ({ ...d, [toolCallId]: approved }));

  const allDecided = () =>
    props.approvals.every((a) => a.toolCallId in decisions());

  async function submit() {
    if (!allDecided() || submitting()) return;
    setSubmitting(true);
    const payload: ApprovalDecision[] = props.approvals.map((a) => ({
      tool_call_id: a.toolCallId,
      approved: decisions()[a.toolCallId],
      scope: grant.scope(a.name, decisions()[a.toolCallId]),
    }));
    try {
      await props.onSubmit(payload);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Panel label="APPROVAL REQUIRED" flush>
      <Stack gap={3} class="p-3">
        <For each={props.approvals}>
          {(approval) => {
            const decision = () => decisions()[approval.toolCallId];
            return (
              <Stack gap={2} class="border-b border-line pb-3 last:border-0">
                <Row gap={2} align="center">
                  <StatusFlag status="warn" dot>
                    {approval.name}
                  </StatusFlag>
                  <Show when={approval.toolCallId in decisions()}>
                    <StatusFlag status={decision() ? "nominal" : "alert"}>
                      {decision() ? "APPROVED" : "DENIED"}
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
                <Show
                  when={!approval.stale}
                  fallback={
                    <Text variant="micro" tone="dim">
                      DECIDED ELSEWHERE — this was resolved from another
                      session; the transcript will catch up shortly.
                    </Text>
                  }
                >
                  <Row gap={2}>
                    <Button
                      variant="primary"
                      size="sm"
                      leading="check"
                      onClick={() => decide(approval.toolCallId, true)}
                    >
                      APPROVE
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      leading="close"
                      onClick={() => decide(approval.toolCallId, false)}
                    >
                      DENY
                    </Button>
                  </Row>
                  <ConversationGrantToggle
                    checked={grant.isAllowed(approval.name)}
                    onChange={(v) => grant.set(approval.name, v)}
                  />
                </Show>
              </Stack>
            );
          }}
        </For>
        <Show when={!stale()}>
          <Row justify="end">
            <Button
              variant="primary"
              disabled={!allDecided() || submitting()}
              onClick={submit}
            >
              {submitting() ? "SUBMITTING…" : "SUBMIT DECISION"}
            </Button>
          </Row>
        </Show>
      </Stack>
    </Panel>
  );
}
