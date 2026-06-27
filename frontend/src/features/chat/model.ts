/** Chat feature data contracts. This is the SEAM: screens depend on these
 *  types, `data.ts` maps backend responses/events to them — so screens don't
 *  change when the mapping behind them does. */

import type { ContextWindow } from "~/lib/stream";

/** The context-window state, derived and emitted by the backend (live over the
 *  run stream, or reconstructed on conversation load). Purely a carrier — the
 *  UI renders it, it does not compute it. */
export type ContextUsage = ContextWindow;

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

/** A static snapshot version of the conversation's View (`view.version`). The
 *  comparable history the operator can flip back through. Bytes at
 *  `/views/{versionId}/content`. */
export interface ViewVersionRef {
  versionId: string;
  title: string;
  filename: string;
  contentType: string;
  kind: "html" | "image" | "text" | "other";
}

/** The live, interactive head of the View — a running server (`view.live`). */
export interface ViewLiveRef {
  url: string;
  title?: string;
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
/** A snapshot version the agent added to the View during the turn. Rendered in the
 *  transcript as a compact chip that opens it in the viewport. */
export interface ViewVersionBlock {
  kind: "view_version";
  id: string;
  version: ViewVersionRef;
}
/** The View's live head, started during the turn. Rendered as a compact LIVE chip
 *  that opens the viewport. */
export interface ViewLiveBlock {
  kind: "view_live";
  id: string;
  live: ViewLiveRef;
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
  model: string;
  messages: ChatMessage[];
  /** Context-window state reconstructed from the thread's last turn, or null
   *  when unavailable. Seeds the header meter on load. */
  context: ContextUsage | null;
  /** Set only while a turn is still streaming server-side; null otherwise. */
  activeRun: ActiveRun | null;
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
