import { For, Show, createEffect, createSignal, type JSX } from "solid-js";
import { Button, Panel, Row, Stack, StatusFlag, Text, type Status } from "~/ui";
import { HOST_COMMAND_TOOL } from "../data";
import type { ApprovalDecision, HostCommand, HostCommandPhase } from "../model";
import {
  ConversationGrantToggle,
  createGrantToggle,
} from "./ConversationGrantToggle";

const phaseFlag: Record<HostCommandPhase, { status: Status; label: string }> = {
  pending: { status: "warn", label: "AWAITING APPROVAL" },
  running: { status: "info", label: "RUNNING" },
  ok: { status: "nominal", label: "OK" },
  error: { status: "alert", label: "FAILED" },
  denied: { status: "alert", label: "DENIED" },
  stale: { status: "idle", label: "DECIDED ELSEWHERE" },
};

/**
 * Host-machine commands rendered as persistent terminals. Each block shows the
 * exact command the agent wants to run on the operator's real host, gates it
 * behind APPROVE/DENY, and — once approved — keeps the same block to show the
 * runtime output (stdout/stderr/exit). The block never collapses into a separate
 * tool card, so the operator keeps one continuous readout of what ran.
 *
 * The backend resumes the parked run only on a decision covering *every* pending
 * command, so decisions are collected and submitted as a single batch once all
 * pending commands are answered. (Today `run_host_command` is the only
 * approval-gated tool, so a park is always exactly this set.)
 */
export function HostCommandCard(props: {
  commands: HostCommand[];
  onSubmit: (decisions: ApprovalDecision[]) => void | Promise<void>;
  /** Controls the runtime-output collapse (expand-all/collapse-all). Defaults to
   *  expanded; the command line and decision controls always stay visible. */
  open?: boolean;
}): JSX.Element {
  // Each decision captures its grant scope at the instant that command is decided,
  // not at batch-submit — so toggling the checkbox after a command is approved can't
  // retroactively change (or lose) that command's already-locked grant choice.
  type Decision = { approved: boolean; scope: ApprovalDecision["scope"] };
  const [decisions, setDecisions] = createSignal<Record<string, Decision>>({});
  const grant = createGrantToggle();
  const [submitting, setSubmitting] = createSignal(false);

  const pending = () => props.commands.filter((c) => c.phase === "pending");
  const isComplete = (d: Record<string, Decision>) =>
    pending().every((c) => c.toolCallId in d);
  const allDecided = () => isComplete(decisions());

  async function decide(toolCallId: string, approved: boolean): Promise<void> {
    if (submitting()) return;
    // Lock in this command's grant choice now (host commands are all one tool, so the
    // opt-in is keyed by that tool name) rather than re-reading the checkbox at submit.
    const next = {
      ...decisions(),
      [toolCallId]: {
        approved,
        scope: grant.scope(HOST_COMMAND_TOOL, approved),
      },
    };
    setDecisions(next);
    // Hold until every pending command is answered, then submit them together —
    // the resume requires decisions covering exactly the pending calls.
    if (!isComplete(next)) return;
    setSubmitting(true);
    const payload: ApprovalDecision[] = Object.entries(next).map(
      ([tool_call_id, d]) => ({
        tool_call_id,
        approved: d.approved,
        scope: d.scope,
      }),
    );
    try {
      await props.onSubmit(payload);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap={2}>
      <For each={props.commands}>
        {(command) => (
          <Terminal
            command={command}
            decided={decisions()[command.toolCallId]?.approved}
            held={command.toolCallId in decisions() && !allDecided()}
            submitting={submitting()}
            open={props.open}
            sessionAllowed={grant.isAllowed(HOST_COMMAND_TOOL)}
            onToggleSession={(v) => grant.set(HOST_COMMAND_TOOL, v)}
            onDecide={decide}
          />
        )}
      </For>
    </Stack>
  );
}

/** A single host command as a terminal: command line, decision (while pending),
 *  then runtime output once it has run. */
function Terminal(props: {
  command: HostCommand;
  decided?: boolean;
  /** Decided locally, but the batch is held until sibling commands are decided. */
  held?: boolean;
  submitting?: boolean;
  /** When defined, controls the runtime-output collapse; defaults to expanded. */
  open?: boolean;
  /** Whether approving this command also grants it for the rest of the conversation. */
  sessionAllowed?: boolean;
  onToggleSession?: (allow: boolean) => void;
  onDecide: (toolCallId: string, approved: boolean) => void;
}): JSX.Element {
  const c = () => props.command;
  const flag = () => phaseFlag[c().phase];
  const [showOutput, setShowOutput] = createSignal(true);
  createEffect(() => {
    if (props.open !== undefined) setShowOutput(props.open);
  });
  // Decided locally, before the optimistic transition off "pending".
  const decidedPending = () =>
    c().phase === "pending" && props.decided !== undefined;
  const hasOutput = () =>
    c().stdout != null ||
    c().stderr != null ||
    c().error != null ||
    c().exitCode != null;

  return (
    <Panel
      label="HOST COMMAND"
      meta={
        <StatusFlag status={flag().status} dot>
          {flag().label}
        </StatusFlag>
      }
      flush
    >
      <Stack gap={2} class="bg-bg p-2">
        {/* The exact command line the agent asked to run on the host. */}
        <Row gap={2} align="start">
          <Text variant="body" tone="nominal" class="shrink-0">
            $
          </Text>
          <Text
            variant="body"
            tone="bright"
            class="whitespace-pre-wrap break-all"
          >
            {c().command}
          </Text>
        </Row>

        {/* Pending: the operator's judgment aid, then the decision. */}
        <Show when={c().phase === "pending"}>
          <Show when={c().explanation}>
            <Text variant="micro" tone="dim" class="break-words">
              {c().explanation}
            </Text>
          </Show>
          <Show
            when={!decidedPending()}
            fallback={
              <Text variant="micro" tone="dim">
                {props.decided ? "APPROVED" : "DENIED"} —{" "}
                {props.held ? "awaiting the other decisions…" : "submitting…"}
              </Text>
            }
          >
            <Stack gap={2}>
              {/* The grant opt-in sits *above* the decision so it reads naturally; its
                  state is captured into this command's decision the moment APPROVE is
                  clicked (see `decide`), so set it before approving. */}
              <ConversationGrantToggle
                checked={props.sessionAllowed}
                disabled={props.submitting}
                onChange={(v) => props.onToggleSession?.(v)}
              />
              <Row gap={2}>
                <Button
                  variant="primary"
                  size="sm"
                  leading="check"
                  disabled={props.submitting}
                  onClick={() => props.onDecide(c().toolCallId, true)}
                >
                  APPROVE & RUN
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  leading="close"
                  disabled={props.submitting}
                  onClick={() => props.onDecide(c().toolCallId, false)}
                >
                  DENY
                </Button>
              </Row>
            </Stack>
          </Show>
        </Show>

        {/* Approved and executing on the host — text readout, never a spinner. */}
        <Show when={c().phase === "running"}>
          <Text variant="micro" tone="info">
            RUNNING ON HOST…
          </Text>
        </Show>

        {/* Denied — it never ran. */}
        <Show when={c().phase === "denied"}>
          <Text variant="micro" tone="alert">
            DENIED — not executed.
          </Text>
        </Show>

        {/* This decision 409'd — already resolved elsewhere (a second tab, a
            retried request) by the time it landed. Non-interactive; the
            transcript reconciles with the actual outcome via a refetch. */}
        <Show when={c().phase === "stale"}>
          <Text variant="micro" tone="dim">
            DECIDED ELSEWHERE — this was resolved from another session; the
            transcript will catch up shortly.
          </Text>
        </Show>

        {/* Runtime output, once the command has run. */}
        <Show when={hasOutput() && showOutput()}>
          <div class="border-t border-line" />
          <Stack gap={1}>
            <Show when={c().stdout}>
              <Text
                variant="micro"
                tone="default"
                class="whitespace-pre-wrap break-all"
              >
                {c().stdout}
              </Text>
            </Show>
            <Show when={c().stderr}>
              <Text
                variant="micro"
                tone="alert"
                class="whitespace-pre-wrap break-all"
              >
                {c().stderr}
              </Text>
            </Show>
            <Show when={c().error}>
              <Text variant="micro" tone="warn" class="break-words">
                {c().error}
              </Text>
            </Show>
            <Show when={c().exitCode != null}>
              <Text variant="micro" tone={c().exitCode === 0 ? "dim" : "alert"}>
                {c().timedOut ? "TIMED OUT · " : ""}EXIT {c().exitCode}
              </Text>
            </Show>
          </Stack>
        </Show>
      </Stack>
    </Panel>
  );
}
