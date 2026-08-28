/** Tasks / Scheduling feature data contracts — mirrors the backend wire contract
 *  (`ScheduledTask`/`TaskRun`, `routes/tasks.py`) camelCase-for-camelCase. */

export type TaskKind = "agent" | "reminder";
export type ScheduleType = "once" | "interval" | "cron" | "webhook";
export type OutputChannel = "chat" | "notification";
export type TaskRunOutcome =
  "ok" | "error" | "blocked" | "cancelled" | "skipped";

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

/** One tool a task may pre-authorize, exactly as `GET /tools/approval-scopes`
 *  serves it.
 *
 *  These are the SAME tool-name identifiers the approval-grant surface uses
 *  (`ApprovalGrant.tool_name`) — not a parallel vocabulary. The list is fetched
 *  rather than declared here because the backend derives it from three sources
 *  that change independently, one of which (the operator's own MCP servers and
 *  connectors) doesn't exist until they register it. */
export interface ApprovalScope {
  name: string;
  category: string;
  description: string;
}
