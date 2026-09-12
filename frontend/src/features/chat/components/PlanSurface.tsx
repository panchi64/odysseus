import { createSignal, For, Show, type JSX } from "solid-js";
import { Markdown, Stack, StatusFlag, Text } from "~/ui";
import type { ApprovalDecision, PlanDocument, PlanStatus } from "../model";
import type { Park } from "../stream/approvals";
import { ApprovalPanel } from "./ApprovalPanel";

/** How each state reads, and how loudly. `pending` is the only one that is a question;
 *  the rest are a record of one already answered, and record-shaped states stay quiet. */
const STATUS: Record<
  PlanStatus,
  { label: string; tone: "warn" | "nominal" | "alert" | "idle" }
> = {
  pending: { label: "Awaiting your approval", tone: "warn" },
  approved: { label: "Approved", tone: "nominal" },
  revising: { label: "Revising", tone: "idle" },
  denied: { label: "Rejected", tone: "alert" },
};

/**
 * **The plan the agent wants to carry out, and the operator's answer to it.**
 *
 * A panel rather than a strip, and read rather than glanced at: this is the document the
 * whole of plan mode exists to produce, and the operator is deciding on the strength of
 * it alone. It gets the width to be read in.
 *
 * **The decision is rendered here, not in the dock.** Every other approval takes over the
 * composer, which is right for a one-line question about a command — the operator's
 * attention and the run's next step in the same place. A plan is not that: answering it
 * means reading several hundred words first, and a decision docked at the bottom of the
 * window while the thing it is about is in a panel beside it puts the question and its
 * subject in two places. So the panel holds both, and `ParkDock` steps back to its Stop
 * control while it does.
 *
 * It is still the *same* park and the same single submission — `ApprovalPanel` reports
 * upward exactly as it does in the dock, and the run resumes once, on one body covering
 * every call it stopped for.
 */
export function PlanSurface(props: {
  plan: () => PlanDocument | null;
  /** The live park, when the run is waiting on this plan. */
  park: () => Park | null;
  onSubmit: (decisions: ApprovalDecision[]) => void | Promise<void>;
}): JSX.Element {
  // The approval and the document are two readings of the same submission, arriving by
  // different routes (the park off the transcript, the plan off `plan.updated`). The
  // decision is only offered when both are in hand and the stored plan still says it is
  // waiting — a park matched against an already-answered plan would be asking a question
  // the backend has the answer to.
  const awaiting = () =>
    props.plan()?.status === "pending"
      ? (props.park()?.planApproval ?? null)
      : null;

  // One submission per park, exactly as the dock guards itself. The three buttons decide
  // and send in one gesture, so an operator who clicks Approve and immediately changes
  // their mind to Reject would otherwise post twice — and the second lands on a run that
  // has already resumed, which comes back 409 and marks the park stale over a decision
  // that in fact succeeded.
  const [submitting, setSubmitting] = createSignal(false);
  const submit = async (decisions: ApprovalDecision[]) => {
    if (submitting()) return;
    setSubmitting(true);
    try {
      await props.onSubmit(decisions);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Show
      when={props.plan()}
      keyed
      fallback={
        <div class="flex h-full items-center justify-center p-4">
          <Text variant="micro" tone="dim">
            No plan for this conversation.
          </Text>
        </div>
      }
    >
      {(plan) => (
        <div class="flex h-full flex-col overflow-y-auto">
          <Stack gap={3} class="p-4">
            <Stack gap={2}>
              <StatusFlag status={STATUS[plan.status].tone} dot>
                {STATUS[plan.status].label}
              </StatusFlag>
              <Text variant="readout" tone="bright">
                {plan.title}
              </Text>
            </Stack>

            <Markdown>{plan.body}</Markdown>

            <Show when={plan.steps.length > 0}>
              <Stack gap={2}>
                <Text variant="label" tone="dim">
                  STEPS
                </Text>
                {/* Numbered, because the order is part of what is being agreed — and
                    because on approval these become the thread's task list in exactly
                    this order. */}
                <ol class="flex list-decimal flex-col gap-1 pl-5">
                  <For each={plan.steps}>
                    {(step) => (
                      <li>
                        <Text variant="body">{step}</Text>
                      </li>
                    )}
                  </For>
                </ol>
              </Stack>
            </Show>

            <Show when={awaiting()} keyed>
              {(approval) => (
                <Show
                  when={!props.park()?.stale}
                  fallback={
                    <Text variant="micro" tone="dim">
                      ANSWERED ELSEWHERE — this was settled from another
                      session; the transcript will catch up shortly.
                    </Text>
                  }
                >
                  <div class="border-line border-t pt-3">
                    <ApprovalPanel
                      approvals={[approval]}
                      revisable
                      hideGrant
                      // The plan is already the whole panel above; repeating it as
                      // `formatArgs` output under the buttons would be the same document
                      // twice, once unreadably.
                      renderBody={() => <></>}
                      onChange={(decisions, allDecided) => {
                        if (allDecided) void submit(decisions);
                      }}
                    />
                  </div>
                </Show>
              )}
            </Show>
          </Stack>
        </div>
      )}
    </Show>
  );
}
