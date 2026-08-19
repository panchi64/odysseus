import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { Panel, Row, StatusFlag, Text } from "~/ui";
import type { PlanItem } from "~/lib/stream";

/** State flag per task. Semantic color is rationed (§4): a pending task is idle
 *  (neutral), and only the task actually running earns an accent. */
const FLAG: Record<
  PlanItem["status"],
  { status: "idle" | "nominal" | "warn" | "alert"; label: string }
> = {
  pending: { status: "idle", label: "PENDING" },
  in_progress: { status: "warn", label: "ACTIVE" },
  completed: { status: "nominal", label: "DONE" },
  cancelled: { status: "idle", label: "CANCELLED" },
  blocked: { status: "alert", label: "BLOCKED" },
};

/** The agent's task list for this thread.
 *
 *  Collapsed to a single readout line by default, because that is the state the operator
 *  glances at repeatedly — a full list would push the conversation off screen every turn.
 *  It expands on click; the header alone carries the count and the running task, so the
 *  collapsed form is a readout rather than a teaser.
 *
 *  Presentation only: the backend owns the list and nothing here can change it. There is
 *  deliberately no edit affordance — the plan is the agent's account of its own work, and
 *  an operator edit would silently disagree with what the model reads back.
 */
export function PlanPanel(props: { items: () => PlanItem[] }): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);

  const items = () => props.items();
  const active = createMemo(() =>
    items().find((i) => i.status === "in_progress"),
  );
  const done = createMemo(
    () => items().filter((i) => i.status === "completed").length,
  );
  // Cancelled tasks leave the denominator: the question the count answers is "how much is
  // left to do", and a cancelled task is not left to do.
  const total = createMemo(
    () => items().filter((i) => i.status !== "cancelled").length,
  );

  return (
    <Show when={items().length > 0}>
      <Panel
        label="PLAN"
        flush
        meta={
          <Row gap={2} align="center">
            {/* Tabular figures line up as the count changes mid-turn (§3). */}
            <Text variant="label" tone="bright" class="tabular-nums">
              {done()}/{total()}
            </Text>
            <Show when={active()} fallback={<StatusFlag>IDLE</StatusFlag>}>
              <StatusFlag status="warn" dot pulse>
                ACTIVE
              </StatusFlag>
            </Show>
          </Row>
        }
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 px-3 py-2 text-left"
          aria-expanded={expanded()}
          aria-label={expanded() ? "Collapse plan" : "Expand plan"}
          onClick={() => setExpanded((v) => !v)}
        >
          {/* The running task's present-tense label when the model gave one — it reads
              as status ("Reading the config") where the imperative content would not. */}
          <Text
            variant="body"
            tone={active() ? "bright" : "dim"}
            class="truncate"
          >
            {active()
              ? (active()?.active_form ?? active()?.content)
              : `${items().length} tasks`}
          </Text>
        </button>
        <Show when={expanded()}>
          <ol class="border-t border-line">
            <For each={items()}>
              {(task) => (
                <li class="border-b border-line last:border-0">
                  <Row gap={2} align="center" class="px-3 py-1">
                    <StatusFlag
                      status={FLAG[task.status].status}
                      dot={task.status === "in_progress"}
                    >
                      {FLAG[task.status].label}
                    </StatusFlag>
                    <Text
                      variant="body"
                      tone={
                        task.status === "in_progress"
                          ? "bright"
                          : task.status === "pending"
                            ? "default"
                            : "dim"
                      }
                    >
                      {task.content}
                    </Text>
                  </Row>
                </li>
              )}
            </For>
          </ol>
        </Show>
      </Panel>
    </Show>
  );
}
