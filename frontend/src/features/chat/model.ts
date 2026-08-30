/** Chat feature data contracts. This is the SEAM: screens depend on these
 *  types, `data.ts` maps backend responses/events to them — so screens don't
 *  change when the mapping behind them does. */

import type { ContextWindow } from "~/lib/stream";

/** The context-window state, derived and emitted by the backend (live over the
 *  run stream, or reconstructed on conversation load). Purely a carrier — the
 *  UI renders it, it does not compute it. */
export type ContextUsage = ContextWindow;

/** What the thread has cost so far — the readout line under the composer.
 *
 *  **Cumulative over the conversation, not the last run**, and every figure is the
 *  backend's: it counts the active path and measures its own wall-clock, and this is
 *  a carrier for the result. Nothing here is derived in the UI — not the averages,
 *  not the rates, not the ratio. Two sources fill it with the identical shape (the
 *  live `run.metrics` frame and the conversation load's `stats`), so a reload changes
 *  nothing about what the line says.
 *
 *  **`null` means unmeasured, and is not the same as `0`.** A provider that reports
 *  no cache figure, a thread whose turns predate the stopwatch, an endpoint that
 *  leaves token counts at zero — all report null, and the strip omits that segment
 *  rather than printing a number that would read as a measurement. */
export interface ConversationStats {
  /** Completed operator exchanges on the active path. */
  turns: number;
  /** Model round-trips those turns took between them — always ≥ `turns`. */
  steps: number;
  toolCalls: number;
  /** Prompt and generation tokens summed across the path. */
  inputTokens: number | null;
  outputTokens: number | null;
  /** Prompt tokens served from the provider's cache, 0–1. Provider-reported, so
   *  null on the many endpoints that don't send one. */
  cacheHitRatio: number | null;
  /** Wall-clock the model was working, and the tools were running, in ms. */
  llmMs: number | null;
  toolMs: number | null;
  /** Mean time to first content, in ms, over the responses that produced any. */
  ttftAvgMs: number | null;
  /** Generation throughput, output tokens per second of model time. */
  tokensPerSecond: number | null;
}

/** "compaction" is not a turn either party took — it is the chassis marking where the
 *  thread's earlier turns were folded into a summary. Rendered as a full-width divider,
 *  not a bubble; it carries the summary in `content` and has no actions. */
export type Role = "user" | "assistant" | "compaction";

export type ToolStatus = "running" | "ok" | "error";

export interface ToolInvocation {
  id: string;
  /** Namespaced tool name, e.g. "memory.recall". */
  name: string;
  /** Human-readable summary of every argument, shown when the card is expanded. */
  args: string;
  /** The one argument that says what this call is *about* — the path, the query,
   *  the command — for the collapsed row. Undefined when no argument stands out,
   *  in which case the row shows `args` instead. */
  detail?: string;
  status: ToolStatus;
  /** Latest progress note while `status='running'` (`tool.progress`), e.g. the
   *  sandbox spinning up. Reassures the operator the wait is work, not a stall. */
  progress?: string;
  /** What came back, in a few characters — "12 entries", "exit 0". Set on
   *  completion; undefined when the result has no shape worth summarizing. */
  outcome?: string;
  /** Result preview shown when expanded. */
  result?: string;
  /** Error detail shown when status='error'. */
  error?: string;
  elapsedMs?: number;
}

/** A sensitive action the agent paused to ask about (`approval.required`). The
 *  operator approves or denies; the run resumes on the same stream. */
export interface Approval {
  toolCallId: string;
  name: string;
  /** Full call arguments, shown so the operator can judge the action. */
  args: Record<string, unknown>;
  /** One-line summary of what will happen. */
  summary: string;
  /** Longer plain-language explanation, when the tool provides one. */
  explanation?: string;
  /** True once submitting a decision for this approval 409'd — the run had
   *  already resumed elsewhere (a second tab, a retried request) by the time
   *  this decision landed. Non-interactive: a refetch reconciles the transcript
   *  with whatever the winning decision actually did. */
  stale?: boolean;
}

/** Lifecycle of a host-machine command (`run_host_command`) — the one
 *  approval-gated tool that runs on the real host instead of the sandbox. */
export type HostCommandPhase =
  | "pending" // awaiting the operator's approval
  | "running" // approved; executing on the host
  | "ok" // finished, exit 0
  | "error" // finished non-zero, or the launch failed
  | "denied" // the operator refused it
  | "stale"; // a decision 409'd — already resolved elsewhere (see `Approval.stale`)

/** A host shell command rendered as a single persistent terminal: the exact
 *  command, the approval gate, and — once it runs — its captured output. Folded
 *  from the run's `tool.started`/`approval.required`/`tool.completed` events
 *  (warm) or the persisted tool call (cold), all keyed by `toolCallId`. */
export interface HostCommand {
  toolCallId: string;
  /** The exact command line the agent asked to run on the host. */
  command: string;
  /** Plain-language description of the effect, shown for the approval decision. */
  explanation?: string;
  phase: HostCommandPhase;
  /** Captured output streams, present once the command has run. */
  exitCode?: number;
  stdout?: string;
  stderr?: string;
  timedOut?: boolean;
  /** A short failure hint, or a launch error. */
  error?: string;
}

/** How a View version previews on stage: a captured static file rendered by kind,
 *  with its bytes at `/views/{artifactId}/content`. Absent ⇒ a live/auto preview
 *  (a running head, or the frontend auto-picks an entry HTML page from the tree). */
export interface ViewPreviewRef {
  kind: "html" | "image" | "text" | "other";
  artifactId: string;
}

/** The live, interactive head of the View — a running server (`view.live`). */
export interface ViewLiveRef {
  url: string;
  title?: string;
}

/** A **version** of the conversation's View (`view.snapshot`) — minted by a `show`.
 *  A git-style, point-in-time capture of the agent's sandbox tree (its code, browsed
 *  and diffed via `/views/snapshots/{id}/…`) plus how it previews. Conversation-scoped
 *  (the panel reads it); the inline chip references it by id. `summary` is a compact
 *  change tally, e.g. `"+2 ~1 -0"`. */
export interface ViewSnapshotRef {
  snapshotId: string;
  title?: string;
  createdAt: string;
  filesChanged: number;
  summary: string;
  /** The static preview the version was shown with, or null for a live/auto preview. */
  preview: ViewPreviewRef | null;
  /** Whether the operator has pinned this version as a "keeper" (backend-owned;
   *  `POST /views/snapshots/{id}/keeper`). Optional — absent until wired. */
  keeper?: boolean;
}

/** One file in a workspace snapshot's tree, with its change status vs. the prior
 *  snapshot. */
export interface SnapshotFile {
  path: string;
  status: "added" | "modified" | "unchanged";
}

/** A file's unified diff within a snapshot. `diff` is empty for binary files or
 *  files that didn't change. */
export interface SnapshotDiff {
  path: string;
  status: "added" | "modified" | "removed";
  diff: string;
}

/** One renderable unit of an assistant turn. A turn is an *ordered* list of
 *  these — the agent's true emission sequence (think → tool → text → think →
 *  tool → …), not regrouped into fixed lanes. Thinking and text arrive as deltas
 *  folded onto a trailing block of the same kind; a new block starts whenever the
 *  kind changes, so a turn naturally holds *multiple* thinking blocks interleaved
 *  with tools and text. `id` is stable for keyed rendering. */
export type AssistantBlock =
  | ThinkingBlock
  | TextBlock
  | ToolBlock
  | HostCommandBlock
  | ApprovalBlock
  | ViewVersionBlock
  | ViewLiveBlock;

export type BlockKind = AssistantBlock["kind"];

/** A private reasoning passage (`thinking.delta`). */
export interface ThinkingBlock {
  kind: "thinking";
  id: string;
  text: string;
}
/** A passage of the answer the operator reads (`answer.delta`). */
export interface TextBlock {
  kind: "text";
  id: string;
  text: string;
}
/** A single generic tool invocation, rendered as a call card. */
export interface ToolBlock {
  kind: "tool";
  id: string;
  tool: ToolInvocation;
}
/** A host-machine command, rendered as a persistent terminal. */
export interface HostCommandBlock {
  kind: "host_command";
  id: string;
  command: HostCommand;
}
/** A sensitive action paused for the operator's decision. */
export interface ApprovalBlock {
  kind: "approval";
  id: string;
  approval: Approval;
}
/** An inline chip marking a version the agent `show`ed during the turn — rendered in
 *  the transcript as a compact chip that opens that version in the viewport. The
 *  version itself is conversation-scoped (a `ViewSnapshotRef` in the snapshots list);
 *  the chip only references it by id and labels it. */
export interface ViewVersionBlock {
  kind: "view_version";
  id: string;
  snapshotId: string;
  title?: string;
  /** The preview kind, for the chip icon (null/absent ⇒ a live/auto preview). */
  previewKind?: "html" | "image" | "text" | "other" | null;
}
/** The View's live head, started during the turn. Rendered as a compact LIVE chip
 *  that opens the viewport. */
export interface ViewLiveBlock {
  kind: "view_live";
  id: string;
  live: ViewLiveRef;
}
/** A web source the turn's `web_search`/`web_fetch` calls surfaced
 *  (`citation.added`), rendered as a compact Sources row beneath the answer. Its display
 *  number is its position in that deduped row, so no per-source index is carried. */
export interface Citation {
  url: string;
  title?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  /** User turns: the operator's prompt text. Assistant turns: unused — the
   *  answer lives in the `text` blocks of `blocks` (kept "" so copy/edit/version
   *  paths that touch user content stay role-agnostic). */
  content: string;
  /** Assistant turns: the ordered block sequence (the single source of truth for
   *  what the turn rendered). Absent on user turns. */
  blocks?: AssistantBlock[];
  /** Assistant turns: web sources the turn's `web_search`/`web_fetch` calls
   *  surfaced, in citation order. Absent on user turns and turns with no web
   *  tool use. */
  citations?: Citation[];
  /** True when the run backing this turn ended with `outcome: "blocked"` (a
   *  usage/loop/context/time bound, not a normal finish) — rendered as a
   *  persistent inline notice rather than only the transient `limit.notice`
   *  toast. `blockedDetail` is the human-readable reason. */
  blocked?: boolean;
  blockedDetail?: string;
  /** The run this assistant turn streams from — needed to approve/cancel it. */
  runId?: string;
  /** True while tokens are still streaming in. */
  streaming?: boolean;
  /** True from the moment this turn is submitted until its run's first event
   *  arrives — the backend only emits `run.started` once it clears the
   *  concurrency semaphore, so a turn can sit queued behind other runs for a
   *  while with nothing to show yet. Rendered as an explicit "queued" state
   *  instead of the streaming shimmer, so a wait behind the slot limit doesn't
   *  read as a stalled model. */
  queued?: boolean;
  /** True when the SSE transport exhausted its reconnect budget without a
   *  terminal event — the run may still be alive server-side, but this client
   *  lost its live connection to it. Distinct from `streaming`/settled: the
   *  turn is neither actively updating nor over, so it needs its own re-attach
   *  affordance rather than silently looking finished or frozen. */
  detached?: boolean;
  /** User turns only: this message was sent while a run was still executing and
   *  is queued on that run, waiting to be handed to the model at its next
   *  boundary (mid-run steering). Rendered as a pending "QUEUED" bubble with
   *  edit + withdraw affordances; cleared when `message.injected` promotes it to a
   *  normal user turn. Distinct from the assistant-side `queued` (concurrency
   *  semaphore wait). */
  queuedPending?: boolean;
  /** User turns only: the backend id of the queued message (`message.queued` /
   *  the send response's `queued_message_id`) — the handle `withdrawQueued`
   *  addresses. Kept after injection for event idempotency. */
  queuedMessageId?: string;
  createdAt: string;
  /** Model/endpoint that produced an assistant message. */
  model?: string;
  /** 0-based position of this turn among its sibling versions (branches). */
  versionIndex?: number;
  /** Total sibling versions for this turn (≥1); >1 means it can be cycled. */
  versionCount?: number;
  /** Whether the operator has pinned this turn (backend-owned). */
  pinned?: boolean;
  /** User turns: ids of the uploads attached to this message. Rendered as
   *  read-only chips on the sent turn; absent/empty on assistant turns. */
  attachmentIds?: string[];
  /** Compaction dividers only: what the fold actually cost. `foldedMessages` counts
   *  **messages**, not exchanges — a plain exchange is two of them and a tool-heavy
   *  turn many more, so this is deliberately not called turns; the backend doesn't
   *  count turns at fold time and the divider must not imply it did. `tokensBefore`
   *  estimates the messages that were folded, `tokensAfter` the summary that replaced
   *  them — *not* the next turn's footprint, which also carries whatever tail the
   *  backend retained. Both are coarse char-based proxies, hence the `~` on screen.
   *
   *  The backend always sends all three (0 when it has nothing to report), so read
   *  them with a `> 0` guard, not a presence check. Optional here only so an older
   *  backend still renders the divider. */
  foldedMessages?: number;
  tokensBefore?: number;
  tokensAfter?: number;
}

/** The in-flight run driving a conversation, when one exists. Present on a cold
 *  read taken mid-stream (e.g. a page reload) so the client can reattach to the
 *  live run and replay what it missed instead of rendering a reply-less thread. */
export interface ActiveRun {
  id: string;
  status: string;
  lastSeq: number;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  /** Context-window state reconstructed from the thread's last turn, or null
   *  when unavailable. Seeds the header meter on load. */
  context: ContextUsage | null;
  /** The thread's cumulative readout, rebuilt by the backend from the stored
   *  messages; null for a thread that has never run. Seeds the composer's readout
   *  line on load, so it reports the same totals it did live. */
  stats: ConversationStats | null;
  /** Set only while a turn is still streaming server-side; null otherwise. */
  activeRun: ActiveRun | null;
  /** Workspace snapshots captured across the thread (newest last), seeding the
   *  viewport's git-style history on load. */
  snapshots: ViewSnapshotRef[];
}

/** The backend's status for the run driving a thread, when one is live. The
 *  server derives it from the run registry; the frontend only renders it —
 *  `awaiting_input` is a run parked on the operator's approval decision, the rest
 *  are plain in-flight work. */
export type ChatActivity = "queued" | "running" | "awaiting_input";

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  /** Last-message snippet for preview cards. */
  preview?: string;
  /** The model the conversation last ran on (its most recent answer's model). */
  model?: string;
  /** Set while a run drives this thread; absent when it's idle. */
  activity?: ChatActivity;
}

/** One decision in an approval response (mirrors the backend's shape). */
export interface ApprovalDecision {
  tool_call_id: string;
  approved: boolean;
  message?: string;
  override_args?: Record<string, unknown>;
  /** "conversation" also records an auto-approval grant so this tool isn't
   *  re-prompted for the rest of the conversation; "once" (default) is this
   *  call only. Only acted on by the backend when `approved` is true. */
  scope?: "once" | "conversation";
}

/** A live conversation-scoped tool auto-approval grant — the operator's
 *  visible + revocable record of what auto-approves for the rest of the thread. The
 *  TTL is backend-owned and not surfaced here (the strip shows the tool name only). */
export interface ApprovalGrant {
  /** The namespaced tool name that auto-approves, e.g. "corpus_retrieve". */
  toolName: string;
}

/** A conversation's compaction state — the same shape for both reductions. `override` is
 *  the stored per-chat choice (`null` = inherit the operator's global setting); `effective`
 *  is the resolved on/off the UI renders. The backend owns the resolution — the frontend
 *  only reflects it. */
export interface CompactionState {
  override: boolean | null;
  effective: boolean;
}
