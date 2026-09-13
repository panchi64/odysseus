import { For, Show, type JSX } from "solid-js";
import { Markdown, Stack, StatusFlag, Text } from "~/ui";
import type { PlanDocument, PlanStatus } from "../model";

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
 * **The plan the agent wants to carry out** — the document, read at a panel's width.
 *
 * This is what the whole of plan mode exists to produce, and the operator decides on the
 * strength of it alone, so it gets the room to be read in rather than a card's worth of
 * summary.
 *
 * **The decision is not here.** It used to be: this panel rendered its own
 * `ApprovalPanel`, on the reasoning that a document should be answered where it is read.
 * What that actually bought was one approval answered in a place no other approval lives,
 * a host with no panel (a compare pane) unable to answer at all, and a park split across
 * two surfaces that has to resume on one body. The answer moved back to `ParkDock` with
 * every other approval, and the dock carries a button that opens this panel — so the
 * reading and the deciding are one gesture apart instead of one of them being homeless.
 *
 * What this owes the operator instead is **saying where the plan is up to**. `revising`
 * is a wait on a whole model turn: the agent is writing the next draft, and a panel that
 * only dimmed its status flag left that looking like the interface had lost the buttons.
 */
export function PlanSurface(props: {
  plan: () => PlanDocument | null;
}): JSX.Element {
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
              {/* The one status that is a wait rather than a record. Written out, because
                  the gap between asking for changes and the next draft is a whole model
                  turn and silence over it reads as something having gone wrong. */}
              <Show when={plan.status === "revising"}>
                <Text variant="micro" tone="dim">
                  The agent is writing the next draft — it will be put to you
                  again when it is ready.
                </Text>
              </Show>
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
          </Stack>
        </div>
      )}
    </Show>
  );
}
