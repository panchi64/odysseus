/** Chat feature data contracts. This is the SEAM: screens depend on these
 *  types, `data.ts` maps backend responses/events to them — so screens don't
 *  change when the mapping behind them does. */

export type Role = "user" | "assistant";

export type ToolStatus = "running" | "ok" | "error";

export interface ToolInvocation {
  id: string;
  /** Namespaced tool name, e.g. "memory.recall". */
  name: string;
  /** Human-readable argument summary. */
  args: string;
  status: ToolStatus;
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

/** A file the agent published for preview (`artifact.published`). */
export interface ArtifactRef {
  artifactId: string;
  title: string;
  filename: string;
  contentType: string;
  kind: "html" | "image" | "text" | "other";
}

/** A live server the agent started (`preview.ready`). */
export interface PreviewRef {
  url: string;
  title?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  /** Separate reasoning/thinking stream, rendered apart from the answer. */
  reasoning?: string;
  tools?: ToolInvocation[];
  /** Host-machine commands rendered as live terminals (approval + runtime). */
  hostCommands?: HostCommand[];
  /** Sensitive actions awaiting the operator's decision. */
  approvals?: Approval[];
  /** Files published during this turn. */
  artifacts?: ArtifactRef[];
  /** Live preview surfaced during this turn (replaced/cleared by later events). */
  preview?: PreviewRef | null;
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
}

export interface ChatSession {
  id: string;
  title: string;
  model: string;
  messages: ChatMessage[];
}

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  /** Last-message snippet for preview cards. */
  preview?: string;
  /** Model the conversation is using. */
  model?: string;
}

/** One decision in an approval response (mirrors the backend's shape). */
export interface ApprovalDecision {
  tool_call_id: string;
  approved: boolean;
  message?: string;
  override_args?: Record<string, unknown>;
}
