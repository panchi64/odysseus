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
/** How full a model's context window is after a turn. The backend owns the
 *  whole derivation (used tokens, fraction, severity); clients only render it.
 *  Null on a metrics frame when unmeasurable (no window or no token usage). */
export interface ContextWindow {
  /** Tokens occupying the window (prompt + generation). */
  used: number;
  /** The model's context window. */
  window: number;
  /** How full the window is, 0–1. */
  fraction: number;
  /** Window severity per the backend's thresholds. */
  level: "nominal" | "warn" | "alert";
}

export interface RunMetrics extends Base {
  type: "run.metrics";
  steps: number;
  tool_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  /** The model's context window, when known — the ceiling `context` measures
   *  against. Mirror completeness; the gauge renders the derived `context` field. */
  context_window: number | null;
  /** The context footprint after this turn (last response's prompt + generation).
   *  Mirror completeness; the gauge renders the derived `context` field. */
  context_used: number | null;
  /** The context-window fullness after this turn, or null when unmeasurable. */
  context: ContextWindow | null;
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

// --- View (the conversation's one versioned output surface) ----------------
// The View's live head — a running server reverse-proxied at `url`. `url` already
// carries the entry path when one was given, so it renders the page, not a listing.
export interface ViewLive extends Base {
  type: "view.live";
  conversation_id: string;
  url: string;
  title: string | null;
  command: string;
  port: number;
}
export interface ViewLiveStopped extends Base {
  type: "view.live.stopped";
  conversation_id: string;
}
// A new **version** of the View — minted by a `show`. Captures the agent's sandbox
// tree (the version's code, browsed/diffed via `/views/snapshots/{id}/…`) and how it
// previews: `preview_artifact_id` + `preview_kind` point at the captured-bytes
// preview of a `show(file=…)` (bytes at `/views/{preview_artifact_id}/content`), or
// both null for a live/auto preview. Conversation-scoped (not a message block).
export interface ViewSnapshot extends Base {
  type: "view.snapshot";
  conversation_id: string;
  snapshot_id: string;
  title: string | null;
  created_at: string;
  files_changed: number;
  summary: string;
  preview_kind: "html" | "image" | "text" | "other" | null;
  preview_artifact_id: string | null;
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
  /** "context" = the model's context window was exceeded; the run stops (it isn't
   *  silently degraded). The bound stops mirror backend/runs/events.py. */
  limit:
    | "steps"
    | "tool_calls"
    | "tokens"
    | "time"
    | "loop"
    | "verify"
    | "context";
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
  | ViewLive
  | ViewLiveStopped
  | ViewSnapshot
  | ConversationTitled
  | CitationAdded
  | ApprovalRequired
  | LimitNotice;

/** A run is over after one of these — the stream reader stops. */
export function isTerminal(event: RunEvent): boolean {
  return event.type === "run.ended" || event.type === "run.error";
}
