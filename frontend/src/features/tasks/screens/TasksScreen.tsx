import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  Chip,
  Field,
  Icon,
  InstrumentBand,
  PageHeader,
  Panel,
  Resource,
  Row,
  Stack,
  StatusFlag,
  Text,
  Toggle,
  confirm,
  copyToClipboard,
  toast,
} from "~/ui";
import { relativeTime, timestamp } from "~/lib/format";
import {
  deleteTask,
  refreshTasks,
  runTaskNow,
  rotateWebhook,
  updateTask,
  useScheduledTasks,
} from "../data";
import { TaskFormModal } from "../components/TaskFormModal";
import { TaskRunHistory } from "../components/TaskRunHistory";
import { humanizeSchedule } from "../schedule";
import type { ScheduledTask, TaskKind } from "../model";

const KIND_ICON: Record<TaskKind, "chat" | "bell"> = {
  agent: "chat",
  reminder: "bell",
};

export function TasksScreen(): JSX.Element {
  const tasksResource = useScheduledTasks();

  const [expandedId, setExpandedId] = createSignal<string | null>(null);
  const [formOpen, setFormOpen] = createSignal(false);
  const [editingTask, setEditingTask] = createSignal<ScheduledTask | null>(
    null,
  );
  const [rotatingId, setRotatingId] = createSignal<string | null>(null);

  const tasks = () => tasksResource() ?? [];
  const enabledCount = createMemo(
    () => tasks().filter((t) => t.enabled).length,
  );
  const disabledCount = createMemo(
    () => tasks().filter((t) => !t.enabled).length,
  );
  const webhookCount = createMemo(
    () => tasks().filter((t) => t.schedule.type === "webhook").length,
  );

  function openNew() {
    setEditingTask(null);
    setFormOpen(true);
  }

  function openEdit(task: ScheduledTask) {
    setEditingTask(task);
    setFormOpen(true);
  }

  async function toggleEnabled(task: ScheduledTask) {
    if (task.enabled) {
      const ok = await confirm({
        title: `Disable "${task.title}"?`,
        detail: "This stops all future scheduled runs until re-enabled.",
        confirmLabel: "DISABLE",
        cancelLabel: "KEEP ENABLED",
        tone: "alert",
      });
      if (!ok) return;
    }
    try {
      await updateTask(task.id, { enabled: !task.enabled });
      toast.success(
        task.enabled ? `"${task.title}" disabled.` : `"${task.title}" enabled.`,
      );
    } catch {
      toast.error("Unable to update the task.");
    }
  }

  async function remove(task: ScheduledTask) {
    const ok = await confirm({
      title: `Delete "${task.title}"?`,
      detail:
        "This removes the task and stops all future scheduled runs. This cannot be undone.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    try {
      if (expandedId() === task.id) setExpandedId(null);
      await deleteTask(task.id);
      toast.success(`Task "${task.title}" deleted.`);
    } catch {
      toast.error("Unable to delete the task.");
    }
  }

  async function runNow(task: ScheduledTask) {
    try {
      await runTaskNow(task.id);
      toast.success(`"${task.title}" queued to run now.`);
    } catch {
      toast.error("Unable to run the task now.");
    }
  }

  async function rotate(task: ScheduledTask) {
    const ok = await confirm({
      title: `Rotate webhook for "${task.title}"?`,
      detail:
        "The current URL stops working immediately — update anything that calls it.",
      confirmLabel: "ROTATE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    setRotatingId(task.id);
    try {
      await rotateWebhook(task.id);
      toast.success(`Webhook rotated for "${task.title}".`);
    } catch {
      toast.error("Unable to rotate the webhook.");
    } finally {
      setRotatingId(null);
    }
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="TASKS"
        subtitle="Scheduled automations and delivery targets."
        assetId="AUTO-TSK-01.0"
        actions={
          <Button variant="primary" leading="plus" onClick={openNew}>
            NEW TASK
          </Button>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String(tasks().length) },
          { label: "ENABLED", value: String(enabledCount()), tone: "nominal" },
          {
            label: "DISABLED",
            value: String(disabledCount()),
            tone: disabledCount() > 0 ? "warn" : "dim",
          },
          { label: "WEBHOOKS", value: String(webhookCount()) },
        ]}
      />

      <Resource
        data={tasksResource}
        onRetry={refreshTasks}
        isEmpty={(t) => t.length === 0}
        emptyMessage="NO TASKS"
        emptyHint="No scheduled tasks configured."
        empty={
          <Button variant="default" onClick={openNew}>
            CREATE TASK
          </Button>
        }
      >
        {(loadedTasks) => (
          <Panel flush>
            <For each={loadedTasks()}>
              {(task) => {
                const expanded = () => expandedId() === task.id;
                return (
                  <div class="border-b border-line last:border-b-0">
                    <div
                      class="flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-raised"
                      classList={{ "bg-raised": expanded() }}
                      onClick={() => setExpandedId(expanded() ? null : task.id)}
                    >
                      <div class="flex min-w-0 flex-1 items-center gap-3">
                        <Icon
                          name={KIND_ICON[task.kind]}
                          size={14}
                          class={task.enabled ? "text-bright" : "text-dim"}
                        />
                        <StatusFlag
                          status={task.enabled ? "nominal" : "idle"}
                          dot={task.enabled}
                        >
                          {task.kind.toUpperCase()}
                        </StatusFlag>
                        <Text
                          variant="label"
                          tone={task.enabled ? "bright" : "dim"}
                          class="truncate"
                        >
                          {task.title}
                        </Text>
                      </div>
                      <div class="hidden items-center gap-4 md:flex">
                        <Text variant="micro" tone="dim" class="font-mono">
                          {humanizeSchedule(task.schedule)}
                        </Text>
                        <Show when={task.nextRunAt}>
                          <Text variant="micro" tone="dim">
                            {relativeTime(task.nextRunAt!)}
                          </Text>
                        </Show>
                        <Show when={task.kind === "agent"}>
                          <StatusFlag
                            status={task.enabled ? "nominal" : "idle"}
                          >
                            {task.output.toUpperCase()}
                          </StatusFlag>
                        </Show>
                      </div>
                      <div
                        class="flex items-center gap-2"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          leading="play"
                          onClick={() => void runNow(task)}
                        >
                          RUN NOW
                        </Button>
                        <Toggle
                          checked={task.enabled}
                          onChange={() => void toggleEnabled(task)}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          leading="edit"
                          onClick={(e) => {
                            e.stopPropagation();
                            openEdit(task);
                          }}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          leading="trash"
                          onClick={(e) => {
                            e.stopPropagation();
                            void remove(task);
                          }}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          leading={
                            expanded() ? "chevron-down" : "chevron-right"
                          }
                        />
                      </div>
                    </div>

                    <Show when={expanded()}>
                      <div class="border-t border-line bg-raised px-4 py-3">
                        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <Stack gap={3}>
                            <Field
                              label={
                                task.kind === "agent"
                                  ? "PROMPT"
                                  : "REMINDER TEXT"
                              }
                              value={task.prompt}
                            />
                            <Row gap={4}>
                              <Field
                                label="KIND"
                                value={task.kind.toUpperCase()}
                              />
                              <Field
                                label="SCHEDULE"
                                value={humanizeSchedule(task.schedule)}
                              />
                              <Show when={task.kind === "agent"}>
                                <Field
                                  label="OUTPUT"
                                  value={task.output.toUpperCase()}
                                />
                              </Show>
                            </Row>
                            <Show when={task.preAuthorized.length > 0}>
                              <Stack gap={1}>
                                <Text variant="label" tone="dim">
                                  PRE-AUTHORIZED
                                </Text>
                                <Row gap={2} class="flex-wrap">
                                  <For each={task.preAuthorized}>
                                    {(scope) => <Chip>{scope}</Chip>}
                                  </For>
                                </Row>
                              </Stack>
                            </Show>
                            <Show when={task.nextRunAt}>
                              <Field
                                label="NEXT RUN"
                                value={timestamp(task.nextRunAt!)}
                              />
                            </Show>
                            <Show when={task.lastRunAt}>
                              <Field
                                label="LAST RUN"
                                value={timestamp(task.lastRunAt!)}
                              />
                            </Show>
                            <Show when={task.schedule.type === "webhook"}>
                              <Stack gap={1}>
                                <Text variant="label" tone="dim">
                                  WEBHOOK URL
                                </Text>
                                <Row gap={2} align="center" class="flex-wrap">
                                  <Text
                                    variant="micro"
                                    tone="dim"
                                    class="break-all font-mono"
                                  >
                                    {task.webhookUrl ?? "—"}
                                  </Text>
                                  <Show when={task.webhookUrl}>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      leading="copy"
                                      onClick={() =>
                                        copyToClipboard(
                                          task.webhookUrl!,
                                          "Webhook URL",
                                        )
                                      }
                                    >
                                      COPY
                                    </Button>
                                  </Show>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    leading="refresh"
                                    disabled={rotatingId() === task.id}
                                    onClick={() => void rotate(task)}
                                  >
                                    ROTATE
                                  </Button>
                                </Row>
                              </Stack>
                            </Show>
                          </Stack>

                          <TaskRunHistory taskId={task.id} />
                        </div>
                      </div>
                    </Show>
                  </div>
                );
              }}
            </For>
          </Panel>
        )}
      </Resource>

      <TaskFormModal
        open={formOpen()}
        onClose={() => setFormOpen(false)}
        task={editingTask()}
      />
    </Stack>
  );
}
