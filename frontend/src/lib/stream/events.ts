/**
 * The run event protocol — the client mirror of `backend/runs/events.py` (v1).
 *
 * Every frame on a run's SSE stream is one of these, a flat envelope
 * `{ type, seq, ts, ...payload }`. This is the frozen contract the chat/run
 * controllers fold into their stores; keep it in lockstep with the backend union.
 */

export const PROTOCOL_VERSION = 1;

interface Base {
  seq: number;
  ts: string;
}

// --- Run lifecycle ---------------------------------------------------------
export interface RunStarted extends Base {
  type: "run.started";
  run_id: string;
  kind: string;
  protocol_version: number;
}
export interface RunMetrics extends Base {
  type: "run.metrics";
  steps: number;
  tool_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
}
export interface RunEnded extends Base {
  type: "run.ended";
  outcome: "done" | "blocked" | "cancelled";
  detail: string | null;
}
export interface RunError extends Base {
  type: "run.error";
  message: string;
  kind: string | null;
}

// --- Step boundaries -------------------------------------------------------
export interface StepStarted extends Base {
  type: "step.started";
  index: number;
  title: string | null;
}
export interface StepCompleted extends Base {
  type: "step.completed";
  index: number;
}

// --- Content (reasoning / answer split) ------------------------------------
export interface ThinkingDelta extends Base {
  type: "thinking.delta";
  text: string;
}
export interface AnswerDelta extends Base {
  type: "answer.delta";
  text: string;
}

// --- Tools -----------------------------------------------------------------
export interface ToolStarted extends Base {
  type: "tool.started";
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
}
export interface ToolProgress extends Base {
  type: "tool.progress";
  tool_call_id: string;
  elapsed_s: number | null;
  partial: string | null;
}
export interface ToolCompleted extends Base {
  type: "tool.completed";
  tool_call_id: string;
  name: string;
  result: unknown;
}
export interface ToolFailed extends Base {
  type: "tool.failed";
  tool_call_id: string;
  name: string;
  error: string;
}

// --- Documents -------------------------------------------------------------
export interface DocumentCreated extends Base {
  type: "document.created";
  document_id: string;
  title: string | null;
}
export interface DocumentDelta extends Base {
  type: "document.delta";
  document_id: string;
  text: string;
}
export interface DocumentCommitted extends Base {
  type: "document.committed";
  document_id: string;
  version: number;
}

// --- Artifacts & live previews ---------------------------------------------
export interface ArtifactPublished extends Base {
  type: "artifact.published";
  artifact_id: string;
  conversation_id: string;
  title: string;
  filename: string;
  content_type: string;
  kind: "html" | "image" | "text" | "other";
}
export interface PreviewReady extends Base {
  type: "preview.ready";
  conversation_id: string;
  url: string;
  title: string | null;
  command: string;
  port: number;
}
export interface PreviewStopped extends Base {
  type: "preview.stopped";
  conversation_id: string;
}

// --- Conversation ----------------------------------------------------------
export interface ConversationTitled extends Base {
  type: "conversation.titled";
  conversation_id: string;
  title: string;
}

// --- Notices ---------------------------------------------------------------
export interface CitationAdded extends Base {
  type: "citation.added";
  url: string;
  title: string | null;
  source_index: number | null;
}
export interface ApprovalRequired extends Base {
  type: "approval.required";
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
  summary: string;
  explanation: string | null;
}
export interface LimitNotice extends Base {
  type: "limit.notice";
  limit: "steps" | "tool_calls" | "tokens" | "time";
  message: string;
}

export type RunEvent =
  | RunStarted
  | RunMetrics
  | RunEnded
  | RunError
  | StepStarted
  | StepCompleted
  | ThinkingDelta
  | AnswerDelta
  | ToolStarted
  | ToolProgress
  | ToolCompleted
  | ToolFailed
  | DocumentCreated
  | DocumentDelta
  | DocumentCommitted
  | ArtifactPublished
  | PreviewReady
  | PreviewStopped
  | ConversationTitled
  | CitationAdded
  | ApprovalRequired
  | LimitNotice;

/** A run is over after one of these — the stream reader stops. */
export function isTerminal(event: RunEvent): boolean {
  return event.type === "run.ended" || event.type === "run.error";
}
