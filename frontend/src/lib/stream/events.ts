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
/** What the occupied part of the window is holding, three ways.
 *
 *  The three are exhaustive — the backend scales them to sum to `ContextWindow.used` —
 *  so they can be read as a whole with no unexplained remainder.
 *
 *  Every figure is an **estimate anchored to the provider's total**: no provider reports
 *  a breakdown, so the split is measured backend-side from what it assembled and scaled
 *  to the one number the provider does report. Render them with a `~`. */
export interface ContextComposition {
  /** The standing brief: instructions + system prompt. */
  system: number;
  /** Every tool name, description and JSON schema handed to the model. */
  tools: number;
  /** The conversation itself. */
  messages: number;
  /** The same tokens itemised — one row per tool category, per contributor to the
   *  standing brief, per class of message content. Each belongs to exactly one group,
   *  and a group's segments sum to its total above, so the two resolutions can never
   *  disagree. Empty when the backend could measure the totals but not the detail. */
  segments: ContextSegment[];
}

/** One line item inside a group.
 *
 *  **A segment is here because it weighs something.** The backend emits no zero rows and
 *  no fixed roster: a thread that has called no tools carries no `tool_results` segment,
 *  a catalog with no MCP servers connected carries no `external` one, and each appears
 *  the moment it starts costing the window. So the panel renders whatever arrives — it
 *  never expects a particular id, and it never draws a row for one that didn't come. */
export interface ContextSegment {
  /** A backend slug — a tool category as the operator's own tool settings name it, an
   *  instruction provider, or a message class. The wording is the client's. */
  id: string;
  group: "brief" | "tools" | "messages";
  tokens: number;
  /** The population behind the figure where there is one (tools in a category); null
   *  where counting would be a claim we haven't measured. */
  count: number | null;
}

export interface ContextWindow {
  /** Tokens occupying the window (prompt + generation). */
  used: number;
  /** The model's context window. */
  window: number;
  /** How full the window is, 0–1. */
  fraction: number;
  /** Window severity per the backend's thresholds. */
  level: "nominal" | "warn" | "alert";
  /** What `used` is made of. Null when it couldn't be measured — a thread whose turns
   *  all predate the measurement, or a reload in a process where no turn has run yet.
   *  Absent, never zeroed: a split claiming no tools and no brief would be a confident
   *  lie about the one thing this exists to expose. */
  parts: ContextComposition | null;
}

/** What the thread has cost so far — **cumulative over the conversation**, not the
 *  run. The backend counts the active path and measures its own wall-clock; every
 *  derived figure below (the ratio, the average, the rate) is computed server-side.
 *  Null means unmeasured and is never interchangeable with 0 — see `RunMetrics` in
 *  `backend/runs/events.py`. */
/** What the thread's most recent model request cost, on its own — everything else on
 *  `RunMetrics` is cumulative over the conversation.
 *
 *  The two questions a running total cannot answer: which endpoint served that last
 *  request (a fallback chain's second model disappears into a sum) and how much of its
 *  prompt the provider had cached (a cold turn disappears into a warm average). Null
 *  fields mean the provider reported nothing, never zero. */
export interface LastRequestUsage {
  /** The model that actually answered, prefixed by its provider when one is reported
   *  (`openai:qwen3-32b`). Not necessarily the model the thread is bound to. */
  route: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
}

export interface RunMetrics extends Base {
  type: "run.metrics";
  steps: number;
  tool_calls: number;
  /** Completed operator exchanges, where `steps` counts the model round-trips. */
  turns: number;
  input_tokens: number | null;
  output_tokens: number | null;
  /** Provider-reported cached prompt tokens; null when the endpoint reports none. */
  cache_read_tokens: number | null;
  /** Wall-clock measured by the backend around its own streaming, so it means the
   *  same on every provider. `llm_ms` is the full round-trip, connect and queue
   *  included — the wait the operator actually sat through. */
  llm_ms: number | null;
  tool_ms: number | null;
  ttft_ms_total: number | null;
  ttft_samples: number;
  /** Backend-derived: cached share of prompt tokens (0–1), mean time to first
   *  content, and generation throughput against model time. */
  cache_hit_ratio: number | null;
  ttft_avg_ms: number | null;
  output_tokens_per_second: number | null;
  /** The model's context window, when known — the ceiling `context` measures
   *  against. Mirror completeness; the gauge renders the derived `context` field. */
  context_window: number | null;
  /** The context footprint after this turn (last response's prompt + generation).
   *  Mirror completeness; the gauge renders the derived `context` field. */
  context_used: number | null;
  /** The context-window fullness after this turn, or null when unmeasurable. */
  context: ContextWindow | null;
  /** The last model request on its own. Null on a thread that has never produced a
   *  response; optional here only so an older backend still renders. */
  last_request?: LastRequestUsage | null;
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
  /** Images the call handed back for the model to look at — a screenshot. Base64,
   *  media type alongside; the renderer adds the data-URI scheme. */
  images?: ToolImage[];
}
export interface ToolImage {
  media_type: string;
  data: string;
}
export interface ToolFailed extends Base {
  type: "tool.failed";
  tool_call_id: string;
  name: string;
  error: string;
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

// --- Browser (the agent's own live page) -----------------------------------
// The agent touched a page in this conversation's browser, so there is now something to
// watch. `url` is a token-gated WebSocket path on the API origin carrying JSON frames.
// There is deliberately **no stopped counterpart**: a browser session outlives the run
// that opened it and is reaped between turns, when no run stream exists to carry an
// event. The socket's own `{t:"end"}` message is the stop signal, and
// `GET /browser/stream/{token}/status` answers for a panel whose socket dropped.
export interface BrowserLive extends Base {
  type: "browser.live";
  conversation_id: string;
  url: string;
  page_url: string | null;
  title: string | null;
}

// --- Conversation ----------------------------------------------------------
export interface ConversationTitled extends Base {
  type: "conversation.titled";
  conversation_id: string;
  title: string;
}

/** Why a fold happened. `threshold` is the ordinary one — the projected footprint
 *  reached the operator's percentage before the turn ran. `overflow` is the recovery
 *  path: the provider refused the request as too large, so the chassis folded and
 *  retried inside the same turn. `manual` is COMPACT NOW. The operator reads a very
 *  different story into each, so the wire carries which rather than leaving the UI to
 *  infer it from timing. Mirrors backend/runs/events.py. */
export type CompactionReason = "threshold" | "overflow" | "manual";

/** A fold is starting. Emitted *before* the summarizer call, which can take tens of
 *  seconds on a long thread — without it the turn simply stalls with nothing on
 *  screen, and the only account of the pause arrives after it is over. `messages` and
 *  `tokens_estimate` are what is about to be folded, so the row can say what the wait
 *  is for; the settled figures ride on `conversation.compacted`. */
export interface CompactionStarted extends Base {
  type: "compaction.started";
  conversation_id: string;
  reason: CompactionReason;
  messages: number;
  tokens_estimate: number;
}

/** The thread's earlier turns were folded into a summary before this turn ran,
 *  because its context footprint reached the operator's threshold. Nothing was
 *  deleted — the transcript keeps every turn; this marks where the *model's*
 *  replayed view narrows to `summary` plus the turns after it. Emitted mid-run,
 *  before the answer streams, and persisted as its own message so a reload
 *  renders the same divider. */
export interface ConversationCompacted extends Base {
  type: "conversation.compacted";
  conversation_id: string;
  /** The checkpoint message the summary is stored on — the id the divider is
   *  keyed by, and the same one a cold read returns. */
  message_id: string;
  summary: string;
  /** How many **messages** the summary stands in for, so the divider can say so
   *  without the client counting anything itself. `ModelMessage`s, not exchanges —
   *  a plain exchange is two — so never render this as a turn count. */
  messages_compacted: number;
  /** Coarse char-based estimates of what the fold replaced (`tokens_before`, over
   *  the folded messages) and what replaced it (`tokens_after`, over the stored
   *  summary alone — *not* the next turn's footprint, which also carries whatever
   *  tail the backend retained). Always sent, 0 when there's nothing to report;
   *  optional here only so an older backend still renders. */
  tokens_before?: number | null;
  tokens_after?: number | null;
  /** The rendered turn the divider follows. The backend resolves the position —
   *  a tree node is not a rendered message, so the client would otherwise have to
   *  guess and could land somewhere a reload disagrees with. Null ⇒ append. */
  after_message_id: string | null;
  /** What triggered the fold, paired with the `compaction.started` that opened it.
   *  Optional only so an older backend still renders the divider — it defaults to the
   *  ordinary case there, which is what such a backend could only have meant. */
  reason?: CompactionReason;
}
/** This turn opened another conversation — today only a research thread, started
 *  by `research_start`. The new thread appears in the session list a moment
 *  later; without this it would appear with no account of where it came from.
 *  `relation` says what the new thread is *for*, as a string rather than a union
 *  so a second kind of linked thread is a new value and not a wire change. */
export interface ConversationLinked extends Base {
  type: "conversation.linked";
  conversation_id: string;
  relation: string;
  title: string | null;
}

// --- Context ---------------------------------------------------------------
/** Something the chassis put in front of the model that nobody in the conversation
 *  wrote — a project's instruction files, the skill catalog, the plan reminder, the date.
 *
 *  The context gauge says what these *cost*; this says what they *said*, and when they
 *  arrived. It is emitted as the turn is assembled, so it lands in the work log ahead of
 *  the work it shaped — and it must never render as a tool call: a tool call is the model
 *  reaching out, this is the chassis reaching in.
 *
 *  `contributor` is the same slug `ContextSegment.id` carries for the standing brief's
 *  rows, so the gauge's "Skill catalog · ~4k" and this row are visibly one block seen
 *  from two distances. `placement` is where it landed in the request — `instructions` at
 *  the head (re-sent every turn, invalidating the prompt-prefix cache when it churns) or
 *  `prompt` at the tail of the turn's own message (volatile content kept out of that
 *  cacheable prefix). `tokens` is a coarse estimate over the **whole** block; `text` is
 *  capped for the wire and says so via `truncated`. */
export interface ContextInjected extends Base {
  type: "context.injected";
  contributor: string;
  placement: "instructions" | "prompt";
  tokens: number;
  text: string;
  truncated: boolean;
}

// --- Notices ---------------------------------------------------------------
export interface CitationAdded extends Base {
  type: "citation.added";
  url: string;
  title: string | null;
}
export interface ApprovalRequired extends Base {
  type: "approval.required";
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
  summary: string;
  explanation: string | null;
}
/** One answer offered for a question. */
export interface QuestionOption {
  label: string;
  description: string | null;
}
/** One question the operator is being asked. `multi_select` says whether several of
 *  `options` may be chosen together; writing an answer instead is always allowed and so
 *  is never a flag. */
export interface QuestionSpec {
  question: string;
  options: QuestionOption[];
  multi_select: boolean;
}
/** The turn is parked on the operator answering, not on them permitting.
 *
 *  Its own event rather than an `approval.required` with a different shape: an approval
 *  is a yes or a no about an action already decided on, and a question comes back
 *  carrying a *value* that becomes the tool's result. One event per call, holding every
 *  question in it — the model asks in one go and is answered in one go. */
export interface QuestionAsked extends Base {
  type: "question.asked";
  tool_call_id: string;
  questions: QuestionSpec[];
}
/** An action at the Auto permission level is being ruled on in the operator's place.
 *
 *  Announced *before* it is ruled on, so a review that takes a model call reads as work
 *  in progress rather than as a stalled turn. `summary` is the action's worst case as the
 *  backend extracted it — the same words the reviewer is judging, so the operator and the
 *  model are looking at one description rather than two. */
export interface ReviewStarted extends Base {
  type: "review.started";
  tool_call_id: string;
  name: string;
  summary: string;
}
/** How the review ruled, and on what.
 *
 *  `decision` is what the run then did: `allow` ran the call with no prompt, `ask` parked
 *  it for the operator anyway, `block` refused it outright. It deliberately carries more
 *  than the outcome — `stage` says whether a deterministic allowlist or a model settled
 *  it, and the three axes say what the model saw. "Allowed" alone tells the operator
 *  nothing they can act on; "low risk, neutral authorization, cleared by the shell judge"
 *  lets them tell an over-permissive rule from a well-judged call.
 *
 *  The axes are null when the model stage never ran — the judge cleared it, or there was
 *  nothing to review with. */
export interface ReviewCompleted extends Base {
  type: "review.completed";
  tool_call_id: string;
  name: string;
  decision: "allow" | "ask" | "block";
  stage: "judge" | "reviewer";
  reason: string;
  risk: "low" | "high" | "too_destructive" | null;
  authorization: "explicitly_no" | "neutral" | "explicitly_yes" | null;
  correctness: string | null;
}
/** The operator sent a message while the run was still executing; it is queued
 *  for injection at the run's next model-request boundary. `text` rides inline
 *  so a reattaching client rebuilds the pending bubble purely from replay. */
export interface MessageQueued extends Base {
  type: "message.queued";
  message_id: string;
  text: string;
}
/** The operator rewrote a queued message's text before the run consumed it.
 *  `text` is the full replacement (not a delta), inline so a reattaching client
 *  rebuilds the pending bubble purely from replay. */
export interface MessageEdited extends Base {
  type: "message.edited";
  message_id: string;
  text: string;
}
/** The operator withdrew a queued message before the run consumed it. */
export interface MessageWithdrawn extends Base {
  type: "message.withdrawn";
  message_id: string;
}
/** A queued message was handed to the model (emitted in drain order); from here
 *  on it is part of the turn and persists as a normal user message. */
export interface MessageInjected extends Base {
  type: "message.injected";
  message_id: string;
}
/** One task on the agent's plan for this conversation. `blocked` only occurs when the
 *  backend enables subtasks/dependencies; it is carried here so a future flip of that
 *  switch is a rendering choice rather than a crash. */
export interface PlanItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed" | "cancelled" | "blocked";
  /** Present-tense label for the task while it runs ("Reading the config"). */
  active_form?: string | null;
}
/** The agent's task list changed. Carries the whole list rather than a delta, so
 *  applying it is idempotent on replay and needs no ordering rules. */
export interface PlanUpdated extends Base {
  type: "plan.updated";
  items: PlanItem[];
}
export interface LimitNotice extends Base {
  type: "limit.notice";
  /** "context" = the model's context window was exceeded; the run stops (it isn't
   *  silently degraded). "search" was the deep-research pipeline's two-empty-rounds
   *  abort — nothing emits it now that research is an ordinary thread, and it stays
   *  handled because the wire never narrows. Mirrors backend/runs/events.py. */
  limit:
    | "steps"
    | "tool_calls"
    | "tokens"
    | "time"
    | "loop"
    | "verify"
    | "context"
    | "search";
  message: string;
}

/** The exact `run.ended` detail (and persisted `blocked_reason`) a turn carries when the
 *  provider refused the request as too large and the chassis could not fold its way out.
 *  Exported from `agent/model_errors.py` on the backend and mirrored verbatim here,
 *  because it is the one stop the operator has a *specific* remedy for — the blocked
 *  turn's marker keys its "Compact and retry" control on this string, live and on
 *  reload. Any other stop reads as a plain bound and offers Continue alone. */
export const CONTEXT_OVERFLOW_DETAIL = "context window exceeded";

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
  | ViewLive
  | ViewLiveStopped
  | ViewSnapshot
  | BrowserLive
  | ConversationTitled
  | CompactionStarted
  | ConversationCompacted
  | ConversationLinked
  | ContextInjected
  | CitationAdded
  | ApprovalRequired
  | QuestionAsked
  | ReviewStarted
  | ReviewCompleted
  | MessageQueued
  | MessageEdited
  | MessageWithdrawn
  | MessageInjected
  | PlanUpdated
  | LimitNotice;

/** A run is over after one of these — the stream reader stops. */
export function isTerminal(event: RunEvent): boolean {
  return event.type === "run.ended" || event.type === "run.error";
}
