/**
 * What the backend actually sends — the snake_case shapes, and nothing that interprets
 * them.
 *
 * Kept apart from `mappers.ts` for one reason: these declarations change when the
 * *backend* changes, and the mappers change when the *screen* needs something different
 * from the same payload. A file holding both would be edited from two directions at once,
 * and a reader trying to answer "what does the wire look like" would have to read past the
 * translation to find out.
 *
 * Nothing here is exported past `data/` — the seam types in `../model` are what the rest
 * of the app sees, which is what lets a field be renamed on the wire without the
 * transcript knowing.
 */

import type { ContextWindow, RunMetrics } from "~/lib/stream";
import type {
  ChatActivity,
  SnapshotDiff,
  SnapshotFile,
  ToolInvocation,
} from "../model";

export interface ConversationSummaryDTO {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string | null;
  model: string | null;
  /** The live run's status for this thread (`running`, `queued`,
   *  `awaiting_input`), or null when idle. Registry-derived server-side — the
   *  thread list renders it without opening each conversation. */
  activity?: ChatActivity | null;
  /** The thread's mode, and — for a code thread — the basename of the directory it
   *  works in. Both on the *listing* because the rail's shape depends on them: it
   *  shows one mode at a time and groups code threads by workspace. */
  mode?: string | null;
  workspace?: string | null;
}

/** One image on the wire. The REST detail and the SSE `tool.completed` event carry the
 *  identical shape — deliberately, so `toolImages` is one mapping rather than two that
 *  could drift into disagreeing about the same screenshot. */
export interface ToolImageDTO {
  media_type: string;
  data: string;
}

export interface ToolCallDTO {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: ToolInvocation["status"];
  result?: unknown;
  error?: string | null;
  images?: ToolImageDTO[];
}

/** An inline View chip re-attached to the message that minted it — references the
 *  conversation-scoped version by id (the panel reads its bytes/files). */
export interface MessageVersionRefDTO {
  snapshot_id: string;
  title: string | null;
  preview_kind: "html" | "image" | "text" | "other" | null;
}

export interface ViewSnapshotDTO {
  snapshot_id: string;
  title: string | null;
  created_at: string;
  files_changed: number;
  summary: string;
  preview_kind: "html" | "image" | "text" | "other" | null;
  preview_artifact_id: string | null;
  /** The operator's durable bookmark on this version. Optional on the wire —
   *  older/mocked payloads may omit it. */
  keeper?: boolean;
}

export interface MessageDTO {
  id: string;
  /** "compaction" is a chassis-authored divider, not a turn — the summary the
   *  thread's earlier turns were folded into, carried in `content`. */
  role: "user" | "assistant" | "compaction";
  content: string;
  reasoning?: string | null;
  tools: ToolCallDTO[];
  versions?: MessageVersionRefDTO[];
  created_at?: string | null;
  /** The model that produced this assistant turn. */
  model?: string | null;
  /** 0-based index of this turn among its sibling versions. */
  version_index?: number;
  /** Total sibling versions for this turn (≥1). */
  version_count?: number;
  /** Whether the operator has pinned this turn. */
  pinned?: boolean;
  /** User turns: ids of the uploads attached to this message. */
  attachment_ids?: string[];
  /** Set when the run behind this assistant turn ended blocked (a usage/loop/
   *  context/time bound) — the human-readable reason. */
  blocked_reason?: string | null;
  /** Compaction rows: how many **messages** the summary stands in for (not turns —
   *  the backend counts `ModelMessage`s), an estimate of what was folded, and an
   *  estimate of the summary that replaced it. The backend sends all three as ints
   *  (0 when there's nothing to report); optional here only so an older backend
   *  still renders. Every other row carries 0/0/0. */
  messages_compacted?: number | null;
  tokens_before?: number | null;
  tokens_after?: number | null;
}

export interface ActiveRunDTO {
  id: string;
  status: string;
  last_seq: number;
}

/** The metric fields shared by the live `run.metrics` frame and the conversation
 *  load's `stats` — the same model server-side, so this is the event type minus its
 *  stream envelope rather than a second declaration that could drift from it. */
export type RunMetricsDTO = Omit<RunMetrics, "type" | "seq" | "ts">;

export interface ConversationDetailDTO extends ConversationSummaryDTO {
  messages: MessageDTO[];
  /** Context-window state reconstructed from the last turn's usage; null when
   *  unavailable. Seeds the meter so an existing thread shows fullness on load. */
  context: ContextWindow | null;
  /** The thread's cumulative readout, rebuilt from the stored messages; null for a
   *  thread that has never run. Seeds the line under the composer on load. */
  stats?: RunMetricsDTO | null;
  /** The in-flight run driving this thread, if a turn is still streaming
   *  server-side; absent/null otherwise. Lets a cold read reattach to it. */
  active_run?: ActiveRunDTO | null;
  /** Workspace snapshots captured across the thread (newest last). Conversation-
   *  scoped — not folded onto a message — so the viewport seeds them separately. */
  snapshots?: ViewSnapshotDTO[];
  /** How far the model may go in this thread. Always populated by the backend, which
   *  resolves it through its own registry — so a thread that predates the column
   *  arrives as the level it was effectively running at rather than as nothing. */
  permission_level?: string | null;
}

/** Shape of `run_host_command`'s result; mirrors the tool's return dict. */
export interface HostResult {
  ok?: boolean;
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  timed_out?: boolean;
  error?: string;
}

export interface SnapshotFileDTO {
  path: string;
  status: SnapshotFile["status"];
}

export interface SnapshotDiffDTO {
  path: string;
  status: SnapshotDiff["status"];
  diff: string;
}

export interface OrphanImageAttachmentsDTO {
  upload_ids: string[];
}

export interface ApprovalGrantDTO {
  tool_name: string;
  // The backend also returns `expires_at`; the strip shows only the tool name, so it's
  // intentionally not mapped into the seam type.
}

export interface ChatCreatedDTO {
  run_id: string;
  conversation_id: string;
  /** Set when the send was queued into the conversation's already-live run
   *  (mid-run steering) instead of starting a new one. */
  queued_message_id?: string | null;
}
