import { createEffect, Show, For, type JSX } from "solid-js";
import { createStore } from "solid-js/store";
import {
  Button,
  Checkbox,
  Input,
  Modal,
  Row,
  Select,
  Stack,
  Text,
  Textarea,
  toast,
} from "~/ui";
import { createTask, updateTask, type TaskInput } from "../data";
import { PRE_AUTH_SCOPES } from "../model";
import type {
  OutputChannel,
  ScheduledTask,
  ScheduleType,
  TaskKind,
} from "../model";
import {
  CRON_PATTERN,
  isoToLocalInput,
  secondsToValueUnit,
  UNIT_SECONDS,
  type IntervalUnit,
} from "../schedule";

interface FormState {
  kind: TaskKind;
  title: string;
  prompt: string;
  scheduleType: ScheduleType;
  runAtLocal: string;
  intervalValue: string;
  intervalUnit: IntervalUnit;
  cron: string;
  output: OutputChannel;
  scopes: Set<string>;
  titleError: string;
  scheduleError: string;
}

function blankForm(): FormState {
  return {
    kind: "agent",
    title: "",
    prompt: "",
    scheduleType: "cron",
    runAtLocal: "",
    intervalValue: "1",
    intervalUnit: "hours",
    cron: "",
    output: "chat",
    scopes: new Set(),
    titleError: "",
    scheduleError: "",
  };
}

function formFromTask(task: ScheduledTask): FormState {
  const sched = task.schedule;
  const interval =
    sched.type === "interval" && sched.everySeconds
      ? secondsToValueUnit(sched.everySeconds)
      : { value: "1", unit: "hours" as IntervalUnit };
  return {
    kind: task.kind,
    title: task.title,
    prompt: task.prompt,
    scheduleType: sched.type,
    runAtLocal: sched.runAt ? isoToLocalInput(sched.runAt) : "",
    intervalValue: interval.value,
    intervalUnit: interval.unit,
    cron: sched.cron ?? "",
    output: task.output,
    scopes: new Set(task.preAuthorized),
    titleError: "",
    scheduleError: "",
  };
}

/** Create/edit modal for a scheduled task — the kind toggle (agent/reminder),
 *  schedule builder (once/interval/cron/webhook), output channel, and
 *  pre-authorization scope checkboxes. A `reminder` preset hides the
 *  agent-only fields (output channel, pre-authorized scopes): a reminder never
 *  drives a Run, so neither has meaning for it. */
export function TaskFormModal(props: {
  open: boolean;
  onClose: () => void;
  task: ScheduledTask | null;
}): JSX.Element {
  const [form, setForm] = createStore<FormState>(blankForm());

  createEffect(() => {
    if (!props.open) return;
    setForm(props.task ? formFromTask(props.task) : blankForm());
  });

  const isAgent = () => form.kind === "agent";
  const isEditing = () => props.task !== null;

  function toggleScope(id: string, checked: boolean) {
    setForm("scopes", (prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function validate(): boolean {
    let valid = true;
    if (!form.title.trim()) {
      setForm("titleError", "TITLE is required.");
      valid = false;
    } else {
      setForm("titleError", "");
    }

    if (form.scheduleType === "once" && !form.runAtLocal) {
      setForm("scheduleError", "Pick a date and time.");
      valid = false;
    } else if (form.scheduleType === "interval") {
      const n = Number(form.intervalValue);
      if (!Number.isFinite(n) || n <= 0) {
        setForm("scheduleError", "Enter a positive interval.");
        valid = false;
      } else {
        setForm("scheduleError", "");
      }
    } else if (form.scheduleType === "cron") {
      if (!CRON_PATTERN.test(form.cron.trim())) {
        setForm(
          "scheduleError",
          "Invalid cron expression — expected five space-separated fields (e.g. 0 8 * * *).",
        );
        valid = false;
      } else {
        setForm("scheduleError", "");
      }
    } else {
      setForm("scheduleError", "");
    }
    return valid;
  }

  async function save() {
    if (!validate()) return;

    const schedule: TaskInput["schedule"] =
      form.scheduleType === "once"
        ? { type: "once", runAt: new Date(form.runAtLocal).toISOString() }
        : form.scheduleType === "interval"
          ? {
              type: "interval",
              everySeconds:
                Number(form.intervalValue) * UNIT_SECONDS[form.intervalUnit],
            }
          : form.scheduleType === "cron"
            ? { type: "cron", cron: form.cron.trim() }
            : { type: "webhook" };

    // `output` only has meaning for an agent task (which channel to deliver its
    // run to); a reminder always fires a direct notification per the schedule
    // contract regardless of this field, so it's left at the form default
    // rather than implying a real distinction that doesn't exist.
    const input: TaskInput = {
      kind: form.kind,
      title: form.title.trim(),
      prompt: form.prompt,
      schedule,
      output: form.output,
      preAuthorized: isAgent() ? [...form.scopes] : [],
    };

    try {
      const saved = isEditing()
        ? await updateTask(props.task!.id, input)
        : await createTask(input);
      toast.success(
        isEditing() ? `"${saved.title}" updated.` : `"${saved.title}" created.`,
      );
      props.onClose();
    } catch {
      toast.error(
        isEditing()
          ? "Unable to update the task."
          : "Unable to create the task.",
      );
    }
  }

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title={isEditing() ? "EDIT TASK" : "NEW TASK"}
      class="max-w-lg"
      footer={
        <Row gap={2}>
          <Button variant="ghost" onClick={props.onClose}>
            CANCEL
          </Button>
          <Button variant="primary" leading="check" onClick={() => void save()}>
            SAVE
          </Button>
        </Row>
      }
    >
      <Stack gap={4}>
        <Select
          label="KIND"
          value={form.kind}
          onChange={(v) => setForm("kind", v as TaskKind)}
          disabled={isEditing()}
          hint={
            isEditing() ? "Set at creation — cannot be changed." : undefined
          }
          options={[
            { value: "agent", label: "Agent task" },
            { value: "reminder", label: "Reminder" },
          ]}
        />
        <Stack gap={1}>
          <Input
            label="TITLE *"
            value={form.title}
            onInput={(e) => {
              setForm("title", e.currentTarget.value);
              if (e.currentTarget.value.trim()) setForm("titleError", "");
            }}
            placeholder="Descriptive task title"
          />
          <Show when={form.titleError}>
            <Text variant="micro" tone="alert">
              {form.titleError}
            </Text>
          </Show>
        </Stack>
        <Textarea
          label={isAgent() ? "PROMPT" : "REMINDER TEXT"}
          rows={4}
          value={form.prompt}
          onInput={(e) => setForm("prompt", e.currentTarget.value)}
          hint={
            isAgent()
              ? "Drives a fresh conversation each time this task fires."
              : "Delivered verbatim as the notification body — no AI phrasing."
          }
        />

        <Select
          label="SCHEDULE TYPE"
          value={form.scheduleType}
          onChange={(v) => {
            setForm("scheduleType", v as ScheduleType);
            setForm("scheduleError", "");
          }}
          options={[
            { value: "cron", label: "Cron expression" },
            { value: "interval", label: "Recurring interval" },
            { value: "once", label: "One-time" },
            { value: "webhook", label: "Webhook" },
          ]}
        />

        <Show when={form.scheduleType === "once"}>
          <Stack gap={1}>
            <Input
              type="datetime-local"
              label="RUN AT *"
              value={form.runAtLocal}
              onInput={(e) => {
                setForm("runAtLocal", e.currentTarget.value);
                setForm("scheduleError", "");
              }}
            />
            <Show when={form.scheduleError}>
              <Text variant="micro" tone="alert">
                {form.scheduleError}
              </Text>
            </Show>
          </Stack>
        </Show>

        <Show when={form.scheduleType === "interval"}>
          <Row gap={2} align="end">
            <Input
              type="number"
              min="1"
              label="EVERY *"
              class="w-24"
              value={form.intervalValue}
              onInput={(e) => {
                setForm("intervalValue", e.currentTarget.value);
                setForm("scheduleError", "");
              }}
            />
            <Select
              value={form.intervalUnit}
              onChange={(v) => setForm("intervalUnit", v as IntervalUnit)}
              options={[
                { value: "seconds", label: "Seconds" },
                { value: "minutes", label: "Minutes" },
                { value: "hours", label: "Hours" },
                { value: "days", label: "Days" },
              ]}
            />
          </Row>
          <Show when={form.scheduleError}>
            <Text variant="micro" tone="alert">
              {form.scheduleError}
            </Text>
          </Show>
        </Show>

        <Show when={form.scheduleType === "cron"}>
          <Stack gap={1}>
            <Input
              label="CRON *"
              value={form.cron}
              onInput={(e) => {
                setForm("cron", e.currentTarget.value);
                setForm("scheduleError", "");
              }}
              placeholder="0 8 * * *"
              hint="Five space-separated fields: minute hour day-of-month month day-of-week."
            />
            <Show when={form.scheduleError}>
              <Text variant="micro" tone="alert">
                {form.scheduleError}
              </Text>
            </Show>
          </Stack>
        </Show>

        <Show when={form.scheduleType === "webhook"}>
          <Text variant="micro" tone="dim">
            Fires only when its webhook URL is called — no time-based schedule.
            The URL is generated once this task is saved.
          </Text>
        </Show>

        <Show when={isAgent()}>
          <Select
            label="OUTPUT CHANNEL"
            value={form.output}
            onChange={(v) => setForm("output", v as OutputChannel)}
            options={[
              { value: "chat", label: "Chat (conversation is the artifact)" },
              {
                value: "notification",
                label: "Notification (+ outcome summary)",
              },
            ]}
          />

          <Stack gap={2}>
            <Text variant="label" tone="dim">
              PRE-AUTHORIZED
            </Text>
            <Text variant="micro" tone="dim">
              Sensitive tool calls in this scope run unattended; anything else
              still parks for approval.
            </Text>
            <Stack gap={2}>
              <For each={PRE_AUTH_SCOPES}>
                {(scope) => (
                  <Stack gap={0}>
                    <Checkbox
                      label={scope.label}
                      checked={form.scopes.has(scope.id)}
                      onChange={(checked) => toggleScope(scope.id, checked)}
                    />
                    <Text variant="micro" tone="dim" class="pl-6">
                      {scope.hint}
                    </Text>
                  </Stack>
                )}
              </For>
            </Stack>
          </Stack>
        </Show>
      </Stack>
    </Modal>
  );
}
