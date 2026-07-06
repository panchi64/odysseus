/** Chat feature data contracts. This is the SEAM: screens depend on these
 *  types, `data.ts` maps backend responses/events to them — so screens don't
 *  change when the mapping behind them does. */

import type { ContextWindow } from "~/lib/stream";

/** The context-window state, derived and emitted by the backend (live over the
 *  run stream, or reconstructed on conversation load). Purely a carrier — the
 *  UI renders it, it does not compute it. */
export type ContextUsage = ContextWindow;

/** A run's token counts (`run.metrics.input_tokens`/`output_tokens`), shown
 *  beside the context gauge. Null fields mean the run reported no usage. */
export interface TokenUsage {
  input: number | null;
  output: number | null;
}

export type Role = "user" | "assistant";

export type ToolStatus = "running" | "ok" | "error";

export interface ToolInvocation {
  id: string;
  /** Namespaced tool name, e.g. "memory.recall". */
  name: string;
  /** Human-readable argument summary. */
  args: string;
  status: ToolStatus;
  /** Latest progress note while `status='running'` (`tool.progress`), e.g. the
   *  sandbox spinning up. Reassures the operator the wait is work, not a stall. */
  progress?: string;
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
}

/** Lifecycle of a host-machine command (`run_host_command`) — the one
 *  approval-gated tool that runs on the real host instead of the sandbox. */
export type HostCommandPhase =
  | "pending" // awaiting the operator's approval
  | "running" // approved; executing on the host
  | "ok" // finished, exit 0
  | "error" // finished non-zero, or the launch failed
  | "denied"; // the operator refused it

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
}

/** One **committed version** of a document the agent authored during the thread —
 *  folded into the same versioned View as workspace snapshots. `version` 0 marks an
 *  in-progress/live body (a `document.delta` still streaming before its commit); a
 *  version ≥ 1 is a real, committed version. `origin` records who minted it. */
export interface ViewDocumentRef {
  documentId: string;
  version: number;
  title?: string;
  origin: "user" | "ai" | "extraction";
  body: string;
  /** When this version was minted (ISO), so the View can order document versions and
   *  workspace snapshots into one timeline instead of concatenating them. */
  createdAt: string;
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
  /** Set only while a turn is still streaming server-side; null otherwise. */
  activeRun: ActiveRun | null;
  /** Workspace snapshots captured across the thread (newest last), seeding the
   *  viewport's git-style history on load. */
  snapshots: ViewSnapshotRef[];
  /** Documents the agent authored across the thread, flattened to one entry per
   *  committed version (oldest first), seeding the viewport alongside the snapshots. */
  documents: ViewDocumentRef[];
}

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  /** Last-message snippet for preview cards. */
  preview?: string;
  /** The model the conversation last ran on (its most recent answer's model). */
  model?: string;
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

/** A conversation's tool-result compaction state. `override` is the stored per-chat choice
 *  (`null` = inherit the operator's global setting); `effective` is the resolved on/off the
 *  UI renders. The backend owns the resolution — the frontend only reflects it. */
export interface CompactionState {
  override: boolean | null;
  effective: boolean;
}
