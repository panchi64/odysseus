import { createSignal, For, Show, type JSX } from "solid-js";
import { Button, Row, Stack, StatusFlag, Text, Textarea } from "~/ui";
import { grantKey } from "../commandScope";
import { formatArgs } from "../data";
import type { Approval, ApprovalDecision } from "../model";
import {
  ConversationGrantToggle,
  createGrantToggle,
} from "./ConversationGrantToggle";

/** What the operator said to one call: the verdict, and anything they wrote with it. */
interface Answer {
  approved: boolean;
  /** Only meaningful on a no — see `ApprovalDecision.intent`. */
  intent: "deny" | "revise";
  message?: string;
}

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
 *
 * ── The variants, and why they are props rather than a second component ──
 * A submitted plan is an approval like any other — same park, same resume, same single
 * body — that happens to be read as a document and answered with three words instead of
 * two. Everything that differs is presentation: what the body of the card is, whether a
 * standing grant is even a coherent thing to offer, and whether "revise" is on the table.
 * A separate component for it would be a second copy of the decision state and the emit
 * rule, drifting from this one the first time either changed.
 *
 * Every prop below defaults to what every existing caller already got, so the ordinary
 * approval renders exactly as it did.
 */
export function ApprovalPanel(props: {
  approvals: Approval[];
  /** Collected upward on every change; complete only once every call is decided. */
  onChange: (decisions: ApprovalDecision[], allDecided: boolean) => void;
  /** Replace the raw-argument dump with a reading of the call. For a plan, the plan. */
  renderBody?: (approval: Approval) => JSX.Element;
  /** Offer "revise" beside approve and deny — a no that asks for another version rather
   *  than refusing the act. Only worth offering where trying again is meaningful. */
  revisable?: boolean;
  /** Hide the standing-grant opt-in. A plan is submitted once and answered once; there
   *  is no recurring act for a grant to stand for. */
  hideGrant?: boolean;
}): JSX.Element {
  const [answers, setAnswers] = createSignal<Record<string, Answer>>({});
  const [notes, setNotes] = createSignal<Record<string, string>>({});
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
    const given = answers();
    props.onChange(
      props.approvals
        .filter((a) => a.toolCallId in given)
        .map((a) => {
          const answer = given[a.toolCallId];
          return {
            tool_call_id: a.toolCallId,
            approved: answer.approved,
            scope: grant.scope(keyOf(a), answer.approved),
            // Both only travel on a no, and the backend ignores them on a yes — but
            // sending an intent with an approval would still be saying something that
            // is not true of it.
            ...(answer.approved
              ? {}
              : {
                  intent: answer.intent,
                  message: answer.message || undefined,
                }),
          };
        }),
      props.approvals.every((a) => a.toolCallId in given),
    );
  };

  const decide = (
    toolCallId: string,
    approved: boolean,
    intent: "deny" | "revise" = "deny",
  ) => {
    setAnswers((a) => ({
      ...a,
      [toolCallId]: {
        approved,
        intent,
        // Read at decision time rather than bound: what they wrote is part of the answer
        // they just gave, not a field that goes on changing after they gave it.
        message: notes()[toolCallId]?.trim(),
      },
    }));
    emit();
  };

  return (
    <Stack gap={3}>
      <For each={props.approvals}>
        {(approval) => {
          const answer = () => answers()[approval.toolCallId];
          const verdict = () => {
            const given = answer();
            if (!given) return null;
            if (given.approved) return { tone: "nominal", label: "Approved" };
            return given.intent === "revise"
              ? { tone: "warn", label: "Changes requested" }
              : { tone: "alert", label: "Denied" };
          };
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
                <Show when={verdict()} keyed>
                  {(v) => (
                    <StatusFlag status={v.tone as "nominal" | "alert" | "warn"}>
                      {v.label}
                    </StatusFlag>
                  )}
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
              <Show
                when={props.renderBody}
                fallback={
                  <Show when={Object.keys(approval.args).length > 0}>
                    <Text variant="micro" tone="dim" class="break-words">
                      {formatArgs(approval.args)}
                    </Text>
                  </Show>
                }
                keyed
              >
                {(render) => render(approval)}
              </Show>
              {/* Offered before the buttons, not revealed by one: a note is what the
                  operator is composing *as* they decide, and a box that appeared only
                  after the click would make them decide first and explain second. */}
              <Show when={props.revisable}>
                <Textarea
                  rows={2}
                  placeholder="What should change? (optional — sent with Request changes or Reject)"
                  value={notes()[approval.toolCallId] ?? ""}
                  onInput={(e) =>
                    setNotes((n) => ({
                      ...n,
                      [approval.toolCallId]: e.currentTarget.value,
                    }))
                  }
                />
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
                <Show when={props.revisable}>
                  <Button
                    variant="default"
                    size="sm"
                    leading="edit"
                    onClick={() => decide(approval.toolCallId, false, "revise")}
                  >
                    Request changes
                  </Button>
                </Show>
                <Button
                  variant="danger"
                  size="sm"
                  leading="close"
                  onClick={() => decide(approval.toolCallId, false, "deny")}
                >
                  {props.revisable ? "Reject" : "Deny"}
                </Button>
              </Row>
              <Show when={!props.hideGrant}>
                <ConversationGrantToggle
                  command={commandOf(approval)}
                  checked={grant.isAllowed(keyOf(approval))}
                  onChange={(v) => {
                    grant.set(keyOf(approval), v);
                    emit();
                  }}
                />
              </Show>
            </Stack>
          );
        }}
      </For>
    </Stack>
  );
}
