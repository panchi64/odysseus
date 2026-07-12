/** Tasks / Scheduling feature data contracts — mirrors the backend wire contract
 *  (`ScheduledTask`/`TaskRun`, `routes/tasks.py`) camelCase-for-camelCase. */

export type TaskKind = "agent" | "reminder";
export type ScheduleType = "once" | "interval" | "cron" | "webhook";
export type OutputChannel = "chat" | "notification";
export type TaskRunOutcome =
  | "ok"
  | "error"
  | "blocked"
  | "cancelled"
  | "skipped";

/** Exactly one of `runAt`/`everySeconds`/`cron` is meaningful, selected by `type`;
 *  a `webhook` task uses none of them (it fires only on its hook route). */
export interface TaskSchedule {
  type: ScheduleType;
  /** ISO timestamp — `once` only. */
  runAt?: string;
  /** Interval length in seconds — `interval` only. */
  everySeconds?: number;
  /** Raw cron expression — `cron` only. */
  cron?: string;
}

export interface ScheduledTask {
  id: string;
  kind: TaskKind;
  title: string;
  prompt: string;
  schedule: TaskSchedule;
  output: OutputChannel;
  /** Tool-name scopes (the same vocabulary `ApprovalGrant.tool_name` uses) this
   *  task's unattended runs are pre-authorized for — seeded into a conversation
   *  grant at each execution so out-of-scope sensitive actions still park. */
  preAuthorized: string[];
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  nextRunAt?: string;
  /** Absolute, ready-to-copy URL — present only for `schedule.type === "webhook"`
   *  tasks. `data.ts` composes it from the backend's relative path. */
  webhookUrl?: string;
}

export interface TaskRun {
  id: string;
  taskId: string;
  /** Set only for an `agent` task's execution — the Run it drove. */
  runId?: string;
  conversationId?: string;
  startedAt: string;
  finishedAt?: string;
  /** Null while the execution is still live (between the scheduler's
   *  started-row insert and its finalize) — never null once `finishedAt`
   *  is set. */
  outcome: TaskRunOutcome | null;
  summary?: string;
}

/** One pre-authorization scope offered as a checkbox in the create/edit form.
 *  These are the SAME tool-name identifiers the approval-grant surface already
 *  uses (`services/approval_grants.py`'s `ApprovalGrant.tool_name`, granted via
 *  the conversation grants routes) — not a parallel vocabulary. They cover every
 *  tool that can pause a run for approval today: the always-gated global-recall
 *  trio (`tools/recall_gate.py`), the foreign-document edit gate
 *  (`tools/documents.py`), and the one `requires_approval=True` tool
 *  (`tools/code.py`'s `run_host_command`). */
export interface PreAuthScope {
  id: string;
  label: string;
  hint: string;
}

export const PRE_AUTH_SCOPES: PreAuthScope[] = [
  {
    id: "code_run_host_command",
    label: "Run host commands",
    hint: "Execute commands directly on the host machine.",
  },
  {
    id: "corpus_retrieve",
    label: "Broad knowledge-base search",
    hint: "Search the whole corpus without a specific source.",
  },
  {
    id: "memory_recall",
    label: "Broad memory recall",
    hint: "Recall long-term memory without a specific query scope.",
  },
  {
    id: "conversations_search",
    label: "Search other conversations",
    hint: "Search across the operator's other conversations.",
  },
  {
    id: "document_edit",
    label: "Edit other documents",
    hint: "Edit documents outside this task's own conversation.",
  },
];
