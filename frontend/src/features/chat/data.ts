import {
  createEffect,
  createMemo,
  createResource,
  createRoot,
  createSignal,
  on,
  onCleanup,
  type Accessor,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api, isApiError } from "~/lib/api";
import { readLS, writeLS } from "~/lib/storage";
import {
  setAwaitingApproval,
  setChatBusy,
  setRunErrored,
} from "~/lib/stores/chatActivity";
import { markConversationRead } from "~/lib/stores/notifications";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import {
  StreamDetachedError,
  streamRun,
  type ContextWindow,
  type RunMetrics,
  type PlanItem,
  type RunEvent,
} from "~/lib/stream";
import { applySessionMode, toast } from "~/ui";
import { DEFAULT_SESSION_MODE, sessionMode } from "~/lib/modes";
import type {
  ActiveRun,
  ApprovalDecision,
  ApprovalGrant,
  AssistantBlock,
  ChatActivity,
  ChatMessage,
  ChatSession,
  ChatSummary,
  Citation,
  CompactionState,
  ContextUsage,
  ConversationStats,
  HostCommand,
  HostCommandBlock,
  HostCommandPhase,
  ReviewBlock,
  SessionMode,
  SnapshotDiff,
  SnapshotFile,
  ToolBlock,
  ToolImage,
  ToolInvocation,
  ViewSnapshotRef,
  ViewVersionBlock,
} from "./model";
import {
  DEFAULT_PERMISSION_LEVEL,
  permissionLevel,
  type PermissionLevel,
} from "./model";
import { describeToolArgs, describeToolResult } from "./toolSummary";

/** The one approval-gated tool that runs on the real host (vs. the sandbox). Its
 *  approval + execution render as a single persistent terminal, never a generic
 *  approval card or tool card. */
export const HOST_COMMAND_TOOL = "code_run_host_command";

/** The prompt a "Continue." turn sends — the operator's way to resume a turn that a
 *  bound (inactivity/wall-clock timeout or cancel) stopped before it finished. A plain
 *  user turn on the same conversation, so the model picks up where the prior turn left
 *  off and a small "Continue." bubble appears in the transcript. */
export const CONTINUE_PROMPT = "Continue.";

/* ── Recency-gated resume ─────────────────────────────────────────────────────
   On entry the chat resumes the last conversation only while it's still "warm"
   (last activity within the window); otherwise it opens a fresh composer. */

export const RESUME_WINDOW_MS = 15 * 60 * 1000;

export function isWarm(iso: string, now = Date.now()): boolean {
  const t = new Date(iso).getTime();
  return !Number.isNaN(t) && now - t <= RESUME_WINDOW_MS;
}

/** The session to land on at entry: the newest warm thread, or null = start
 *  fresh. Assumes `list` is newest-first (as the seam returns it). */
export function entrySessionId(list: ChatSummary[]): string | null {
  const warm = list.find((s) => isWarm(s.updatedAt));
  return warm ? warm.id : null;
}

/* ── Pinned threads (non-recency ordering) ────────────────────────────────── */

const PINS_KEY = "ody.chat.pins";
function readPins(): Set<string> {
  try {
    const raw = readLS(PINS_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}
const [_pinned, _setPinned] = createSignal<Set<string>>(readPins());
export const pinnedIds = _pinned;
export function isPinned(id: string): boolean {
  return _pinned().has(id);
}
export function togglePin(id: string): void {
  const next = new Set(_pinned());
  if (next.has(id)) next.delete(id);
  else next.add(id);
  _setPinned(next);
  writeLS(PINS_KEY, JSON.stringify([...next]));
}

/** Pinned threads first (recency preserved within each group). */
export function orderSessions(list: ChatSummary[]): ChatSummary[] {
  const pins = _pinned();
  if (pins.size === 0) return list;
  const pinned = list.filter((s) => pins.has(s.id));
  const rest = list.filter((s) => !pins.has(s.id));
  return [...pinned, ...rest];
}

/* ── Auto-title reveals ───────────────────────────────────────────────────────
   When the backend names a fresh thread it streams `conversation.titled` on the
   run. The title is also persisted (the session list picks it up on the next
   refresh), but the operator never asked for it — so the UI *types it out* rather
   than snapping it in. The freshly-named title is held here, keyed by conversation
   id; the header and its sidebar row reveal it with the typewriter.

   The reveal's lifetime is owned here, in the data layer — not by a mounted
   component's animation-done callback. `revealTitle` schedules the clear up front,
   so an entry can never leak if the operator navigates away mid-reveal, and either
   surface can render it without one having to tell the other when it's done. */

/** Milliseconds per character for a title reveal — shared by the typewriter and
 *  the clear-scheduling below so they stay in lockstep. */
export const REVEAL_SPEED_MS = 30;
// A buffer past the typed-out duration before clearing, so the clear always lands
// after the animation finishes — even for a sidebar row that mounts a beat late
// (a new thread's row appears on the post-turn refresh, just after the header
// began typing). When it clears, both surfaces fall back to the persisted title.
const REVEAL_CLEAR_BUFFER_MS = 1500;

const [titleReveals, setTitleReveals] = createStore<
  Record<string, string | undefined>
>({});
export { titleReveals };

function revealTitle(id: string, title: string): void {
  setTitleReveals(id, title);
  const delay = title.length * REVEAL_SPEED_MS + REVEAL_CLEAR_BUFFER_MS;
  // Idempotent: clearing a since-deleted/renamed thread is a harmless no-op.
  setTimeout(() => setTitleReveals(produce((s) => void delete s[id])), delay);
}

/* ── Cross-surface entry intents ──────────────────────────────────────────────
   The overview launchpad hands the chat screen what to do on arrival. */

interface PendingDraft {
  text: string;
  model: ModelSelection | null;
  /** Ids of uploads attached on the launchpad, carried into the first turn. */
  attachmentIds?: string[];
}

const [_pendingDraft, _setPendingDraft] = createSignal<PendingDraft | null>(
  null,
);

export function startConversation(
  text: string,
  model: ModelSelection | null,
  attachmentIds?: string[],
): void {
  _setPendingDraft({ text, model, attachmentIds });
}
export function consumePendingDraft(): PendingDraft | null {
  const v = _pendingDraft();
  if (v) _setPendingDraft(null);
  return v;
}

const [_requestedSession, _setRequestedSession] = createSignal<string | null>(
  null,
);
export function openConversation(id: string): void {
  _setRequestedSession(id);
}
export function consumeRequestedSession(): string | null {
  const v = _requestedSession();
  if (v) _setRequestedSession(null);
  return v;
}

/* ── Conversation REST → seam types ───────────────────────────────────────── */

interface ConversationSummaryDTO {
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
interface ToolImageDTO {
  media_type: string;
  data: string;
}

interface ToolCallDTO {
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
interface MessageVersionRefDTO {
  snapshot_id: string;
  title: string | null;
  preview_kind: "html" | "image" | "text" | "other" | null;
}

interface ViewSnapshotDTO {
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

interface MessageDTO {
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

interface ActiveRunDTO {
  id: string;
  status: string;
  last_seq: number;
}

/** The metric fields shared by the live `run.metrics` frame and the conversation
 *  load's `stats` — the same model server-side, so this is the event type minus its
 *  stream envelope rather than a second declaration that could drift from it. */
type RunMetricsDTO = Omit<RunMetrics, "type" | "seq" | "ts">;

interface ConversationDetailDTO extends ConversationSummaryDTO {
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

function toActiveRun(dto: ActiveRunDTO | null | undefined): ActiveRun | null {
  return dto ? { id: dto.id, status: dto.status, lastSeq: dto.last_seq } : null;
}

/** The composer's readout, from the backend's metrics payload.
 *
 *  One mapper for both sources on purpose: the live `run.metrics` frame and the
 *  conversation load's `stats` are the *same* shape server-side, so mapping them in
 *  one place is what guarantees a reload can't quietly report something different
 *  from what the stream reported a moment earlier.
 *
 *  A pure rename — no arithmetic. The averages, the rate and the ratio all arrive
 *  derived, because deriving them here would mean two implementations of the same
 *  formula and a second answer to a question the backend already answered. Nulls
 *  pass through untouched: they mean unmeasured, and coercing one to 0 would turn
 *  "nobody reported this" into a measurement. */
function toStats(dto: RunMetricsDTO): ConversationStats {
  return {
    turns: dto.turns,
    steps: dto.steps,
    toolCalls: dto.tool_calls,
    inputTokens: dto.input_tokens,
    outputTokens: dto.output_tokens,
    cacheHitRatio: dto.cache_hit_ratio,
    llmMs: dto.llm_ms,
    toolMs: dto.tool_ms,
    ttftAvgMs: dto.ttft_avg_ms,
    tokensPerSecond: dto.output_tokens_per_second,
    lastRequest: dto.last_request
      ? {
          route: dto.last_request.route,
          inputTokens: dto.last_request.input_tokens,
          outputTokens: dto.last_request.output_tokens,
          cacheReadTokens: dto.last_request.cache_read_tokens,
          cacheWriteTokens: dto.last_request.cache_write_tokens,
        }
      : null,
  };
}

/** A readable one-line title for a thread that the operator hasn't named. */
function deriveTitle(dto: ConversationSummaryDTO): string {
  if (dto.title) return dto.title;
  if (dto.preview) return dto.preview.slice(0, 60);
  return "Untitled conversation";
}

function toSummary(dto: ConversationSummaryDTO): ChatSummary {
  return {
    id: dto.id,
    title: deriveTitle(dto),
    updatedAt: dto.updated_at,
    messageCount: dto.message_count,
    preview: dto.preview ?? undefined,
    model: dto.model ?? undefined,
    activity: dto.activity ?? undefined,
    mode: sessionMode(dto.mode ?? undefined),
    workspace: dto.workspace ?? undefined,
  };
}

/** Format tool args as a compact `k=v` summary for the call card. */
export function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

function stringifyResult(result: unknown): string | undefined {
  if (result == null) return undefined;
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

/** Shape of `run_host_command`'s result; mirrors the tool's return dict. */
interface HostResult {
  ok?: boolean;
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  timed_out?: boolean;
  error?: string;
}

/** Pull the structured streams out of a host command's result, or null when the
 *  payload isn't that shape (e.g. a denial string) — callers leave the phase
 *  untouched in that case so a denied command stays denied. */
function parseHostResult(result: unknown): HostResult | null {
  if (result == null || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;
  const known =
    typeof r.stdout === "string" ||
    typeof r.exit_code === "number" ||
    typeof r.error === "string";
  return known ? (r as HostResult) : null;
}

function hostPhaseFromResult(r: HostResult): HostCommandPhase {
  return r.ok === false || r.error != null ? "error" : "ok";
}

/** Map a persisted host-command tool call (cold history) to the terminal model.
 *  A stored call has already run, so its phase comes from the recorded status. */
function toHostCommand(dto: ToolCallDTO): HostCommand {
  const r = parseHostResult(dto.result);
  // The tool always returns a structured dict when it actually executes, so a
  // plain-string result means it never ran — i.e. it was denied, and the string
  // is the denial message the model was handed. Surface that instead of a green OK.
  const denial =
    !r && typeof dto.result === "string" && dto.result ? dto.result : undefined;
  const phase: HostCommandPhase = denial
    ? "denied"
    : dto.status === "running"
      ? "running"
      : dto.status === "error"
        ? "error"
        : r
          ? hostPhaseFromResult(r)
          : "ok";
  return {
    toolCallId: dto.id,
    command: typeof dto.args.command === "string" ? dto.args.command : "",
    explanation:
      typeof dto.args.explanation === "string"
        ? dto.args.explanation
        : undefined,
    phase,
    exitCode: r?.exit_code,
    stdout: r?.stdout,
    stderr: r?.stderr,
    timedOut: r?.timed_out,
    // Carry whatever diagnostic exists: the result hint, the denial message, or a
    // retry/validation error projected onto the tool call.
    error: r?.error ?? denial ?? dto.error ?? undefined,
  };
}

/** Map a View version DTO/event to the seam type. Shared by the cold read
 *  (conversation detail) and the warm stream (`view.snapshot`). */
function toViewSnapshotRef(dto: ViewSnapshotDTO): ViewSnapshotRef {
  return {
    snapshotId: dto.snapshot_id,
    title: dto.title ?? undefined,
    createdAt: dto.created_at,
    filesChanged: dto.files_changed,
    summary: dto.summary,
    preview:
      dto.preview_artifact_id && dto.preview_kind
        ? { kind: dto.preview_kind, artifactId: dto.preview_artifact_id }
        : null,
    keeper: dto.keeper ?? false,
  };
}

/** The inline transcript chip for a version the agent `show`ed — references the
 *  conversation-scoped version by id. Shared by the cold read and the warm stream. */
function toVersionChipBlock(
  messageId: string,
  ref: {
    snapshotId: string;
    title?: string;
    previewKind?: ViewVersionBlock["previewKind"];
  },
): ViewVersionBlock {
  return {
    kind: "view_version",
    id: `${messageId}-${ref.snapshotId}`,
    snapshotId: ref.snapshotId,
    title: ref.title,
    previewKind: ref.previewKind,
  };
}

/** Derive the citations a completed `web_search`/`web_fetch` tool call surfaced, in
 *  result order — the cold-reload counterpart to the live `citation.added` fold, so a
 *  reloaded transcript shows the same Sources row that streamed in. Cross-call dedup and
 *  the row numbering are the caller's concern (`toMessage` dedups by URL; the row numbers
 *  by position), so this neither dedups nor indexes. Anything else (a degraded-capability
 *  string, a still-running call, an unrecognized shape) yields none.
 *
 *  `web_search` now persists as a `SearchResults` object (`{ instruction, results }`), not
 *  a bare array — read `.results`. `web_fetch` persists as a single page object. */
function citationsFromToolResult(name: string, result: unknown): Citation[] {
  if (name === "web_search") {
    const items = (result as { results?: unknown })?.results;
    if (!Array.isArray(items)) return [];
    const citations: Citation[] = [];
    for (const item of items) {
      if (
        !item ||
        typeof item !== "object" ||
        typeof (item as { url?: unknown }).url !== "string"
      )
        continue;
      const { url, title } = item as { url: string; title?: string };
      citations.push({ url, title });
    }
    return citations;
  }
  if (
    name === "web_fetch" &&
    result &&
    typeof result === "object" &&
    typeof (result as { url?: unknown }).url === "string"
  ) {
    const { url, title } = result as { url: string; title?: string };
    return [{ url, title }];
  }
  return [];
}

/** The wire's snake_case image list as the model's, or undefined when a call returned
 *  none — the same mapping for the live event and the cold DTO, since a screenshot has
 *  to look identical whether the operator watched it happen or reloaded into it. */
function toolImages(
  images: ToolImageDTO[] | undefined,
): ToolImage[] | undefined {
  if (!images?.length) return undefined;
  return images.map((i) => ({ mediaType: i.media_type, data: i.data }));
}

function toTool(dto: ToolCallDTO): ToolInvocation {
  return {
    id: dto.id,
    name: dto.name,
    args: formatArgs(dto.args),
    detail: describeToolArgs(dto.name, dto.args),
    status: dto.status,
    // Only a call that succeeded has an outcome to report; a failure's story is
    // its error, which the card shows in full.
    outcome:
      dto.status === "ok"
        ? describeToolResult(dto.name, dto.result)
        : undefined,
    result: stringifyResult(dto.result),
    error: dto.error ?? undefined,
    images: toolImages(dto.images),
  };
}

function toMessage(dto: MessageDTO): ChatMessage {
  const base: ChatMessage = {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    createdAt: dto.created_at ?? new Date().toISOString(),
    versionIndex: dto.version_index,
    versionCount: dto.version_count,
    pinned: dto.pinned,
    attachmentIds: dto.attachment_ids,
    foldedMessages: dto.messages_compacted ?? undefined,
    tokensBefore: dto.tokens_before ?? undefined,
    tokensAfter: dto.tokens_after ?? undefined,
  };
  if (dto.role !== "assistant") return base;
  // Cold history is still flat (no recorded emission order), so reconstruct the
  // turn's blocks in the legacy lane order — reasoning, the tool/host calls, the
  // version chips, then the answer. (Once the backend persists ordered blocks, map
  // them straight through here; the live stream already carries true order.)
  const blocks: AssistantBlock[] = [];
  const citations: Citation[] = [];
  if (dto.reasoning)
    blocks.push({
      kind: "thinking",
      id: `${dto.id}-reasoning`,
      text: dto.reasoning,
    });
  for (const t of dto.tools) {
    if (t.name === HOST_COMMAND_TOOL)
      blocks.push({
        kind: "host_command",
        id: `${dto.id}-${t.id}`,
        command: toHostCommand(t),
      });
    else
      blocks.push({ kind: "tool", id: `${dto.id}-${t.id}`, tool: toTool(t) });
    for (const c of citationsFromToolResult(t.name, t.result))
      if (!citations.some((existing) => existing.url === c.url))
        citations.push(c);
  }
  for (const v of dto.versions ?? [])
    blocks.push(
      toVersionChipBlock(dto.id, {
        snapshotId: v.snapshot_id,
        title: v.title ?? undefined,
        previewKind: v.preview_kind,
      }),
    );
  if (dto.content)
    blocks.push({ kind: "text", id: `${dto.id}-text`, text: dto.content });
  // The answer lives in the text block(s); keep `content` empty for assistant
  // turns so it isn't a second, divergent copy of the same text.
  return {
    ...base,
    content: "",
    blocks,
    citations: citations.length ? citations : undefined,
    blocked: dto.blocked_reason != null,
    blockedDetail: dto.blocked_reason ?? undefined,
    model: dto.model ?? undefined,
  };
}

/* ── Read accessors (the seam) ────────────────────────────────────────────── */

let refetchSessions: (() => void) | undefined;
let sessionsAccessor: Accessor<ChatSummary[] | undefined> | undefined;

async function fetchSessions(): Promise<ChatSummary[]> {
  const rows = await api.get<ConversationSummaryDTO[]>("/conversations");
  return rows.map(toSummary);
}

/** The app-wide conversation list — one shared resource read by both the chat
 *  room and the nav rail's RECENTS. A singleton (under its own never-disposed
 *  root, like `mainChat`) so the two surfaces can't double-fetch or drift, and so
 *  `refreshSessions()` after a turn updates the single list both render. */
export function useChatSessions(): Accessor<ChatSummary[] | undefined> {
  if (sessionsAccessor) return sessionsAccessor;
  return (sessionsAccessor = createRoot(() => {
    const [data, { refetch }] = createResource(fetchSessions);
    refetchSessions = refetch;
    // Read `.latest`, not the resource itself. `refreshSessions()` runs after every
    // turn and refetches in place; reading the resource under the app's
    // fallback-less root <Suspense> would re-suspend it for the duration of each
    // refetch, blanking the whole page for a frame. `.latest` keeps the prior list
    // on screen while the refetch is in flight, so a finishing stream no longer
    // flickers the page.
    return () => data.latest;
  }));
}

/** Re-read the conversation list (after a turn, rename, or delete). */
export function refreshSessions(): void {
  refetchSessions?.();
}

async function fetchSession(id: string): Promise<ChatSession> {
  const dto = await api.get<ConversationDetailDTO>(`/conversations/${id}`);
  return {
    id: dto.id,
    title: deriveTitle(dto),
    messages: dto.messages.map(toMessage),
    context: dto.context,
    stats: dto.stats ? toStats(dto.stats) : null,
    activeRun: toActiveRun(dto.active_run),
    snapshots: (dto.snapshots ?? []).map(toViewSnapshotRef),
    mode: sessionMode(dto.mode ?? undefined),
    permission: permissionLevel(dto.permission_level ?? undefined),
  };
}

/** Loads a session. A null id means a new, unsaved conversation — the resource
 *  doesn't fetch, so the screen renders an empty thread. */
export function useChatSession(id: () => string | null): Resource<ChatSession> {
  const [data] = createResource(id, fetchSession);
  return data;
}

/* ── Workspace snapshot accessors (git-style history) ─────────────────────────
   The viewport reads a selected snapshot's file tree, a file's bytes, and the
   per-file diffs through these. Auth-gated like the other `/views` endpoints. */

interface SnapshotFileDTO {
  path: string;
  status: SnapshotFile["status"];
}

interface SnapshotDiffDTO {
  path: string;
  status: SnapshotDiff["status"];
  diff: string;
}

/** The files in a snapshot's tree, each with its change status vs. the prior snapshot. */
export async function fetchSnapshotFiles(
  snapshotId: string,
): Promise<SnapshotFile[]> {
  const rows = await api.get<SnapshotFileDTO[]>(
    `/views/snapshots/${snapshotId}/files`,
  );
  return rows.map((r) => ({ path: r.path, status: r.status }));
}

/** A snapshot file's text content. Auth-gated, so the bytes come through the
 *  bearer-aware blob fetch, then decoded as text. */
export async function fetchSnapshotFileText(
  snapshotId: string,
  path: string,
): Promise<string> {
  const blob = await api.getBlob(snapshotFilePath(snapshotId, path));
  return blob.text();
}

/** The path to a snapshot file's raw bytes — fed to the blob fetch / blob-URL hook
 *  (an `<iframe>` can't carry the bearer, so never used as a bare src). */
export function snapshotFilePath(snapshotId: string, path: string): string {
  return `/views/snapshots/${snapshotId}/file?path=${encodeURIComponent(path)}`;
}

/** The per-file unified diffs for a snapshot against a base (empty `diff` for binary
 *  files). With no `baseId`, the backend diffs against the immediately-previous
 *  snapshot; pass an explicit snapshot id to compare against any prior version. */
export async function fetchSnapshotDiffs(
  snapshotId: string,
  baseId?: string,
): Promise<SnapshotDiff[]> {
  const query = baseId ? `?base=${encodeURIComponent(baseId)}` : "";
  const rows = await api.get<SnapshotDiffDTO[]>(
    `/views/snapshots/${snapshotId}/diff${query}`,
  );
  return rows.map((r) => ({ path: r.path, status: r.status, diff: r.diff }));
}

export async function renameConversation(
  id: string,
  title: string,
): Promise<void> {
  await api.patch(`/conversations/${id}`, { title });
  refreshSessions();
}

/** Re-derive a thread's title on demand. The backend names it from every question
 *  the operator asked across the thread (not just the opening line, and never the
 *  assistant's replies), then this reveals the result with the same typewriter
 *  animation as the first-turn auto-title so both surfaces stay in lockstep. */
export async function regenerateTitle(id: string): Promise<void> {
  // Titling resolves the backend `utility`→`main` binding (with its pinned model),
  // the same source every background caller uses — no per-request override needed.
  const summary = await api.post<ConversationSummaryDTO>(
    `/conversations/${id}/retitle`,
    {},
  );
  if (summary.title) revealTitle(id, summary.title);
  refreshSessions();
}

export async function deleteConversation(
  id: string,
  purgeImages = false,
  discardBranch = false,
): Promise<void> {
  const params = [
    purgeImages ? "purgeImages=true" : "",
    // A code thread with unmerged commits is refused unless this says so —
    // the backend decides, this only relays the operator's answer.
    discardBranch ? "discardBranch=true" : "",
  ].filter(Boolean);
  const q = params.length ? `?${params.join("&")}` : "";
  await api.del(`/conversations/${id}${q}`);
  refreshSessions();
}

/** Copy a thread's history up to `messageId` into a new conversation and return
 *  its id. The backend returns the *fork's* detail, so the caller navigates in one
 *  round-trip; the source thread is untouched. */
export async function forkConversation(
  conversationId: string,
  messageId: string,
): Promise<string> {
  const detail = await api.post<ConversationDetailDTO>(
    `/conversations/${conversationId}/messages/${messageId}/fork`,
    {},
  );
  refreshSessions();
  return detail.id;
}

/** What a code thread has changed against its project's base ref. */
export interface BranchState {
  conversationId: string;
  projectId: string;
  branch: string;
  baseRef: string;
  filesChanged: number;
  insertions: number;
  deletions: number;
  patch: string;
  active: boolean;
}

/** The thread's branch, or null when there isn't one to show.
 *
 *  A 404 is the ordinary answer for every chat conversation, not an error. Anything
 *  else degrades to null as well, deliberately: this drives a chip in the conversation
 *  header, and a project directory the operator moved must cost them the chip, not the
 *  whole header. */
export async function fetchBranch(
  conversationId: string,
): Promise<BranchState | null> {
  try {
    return await api.get<BranchState>(`/worktrees/${conversationId}`);
  } catch (err) {
    if (!isApiError(err) || err.status !== 404) {
      console.warn("branch state unavailable", err);
    }
    return null;
  }
}

export async function mergeBranch(conversationId: string): Promise<string> {
  const res = await api.post<{ merged: boolean; detail: string }>(
    `/worktrees/${conversationId}/merge`,
    {},
  );
  return res.detail;
}

export async function discardBranch(conversationId: string): Promise<void> {
  await api.post(`/worktrees/${conversationId}/discard`, {});
}

interface OrphanImageAttachmentsDTO {
  upload_ids: string[];
}

/** Image uploads a pending delete would orphan — ones nothing else references.
 *  Probed before a conversation/message delete so the operator can be offered the
 *  keep-or-purge choice. Empty ⇒ nothing would be left unused, delete outright.
 *  Omit `messageId` for a whole-conversation delete. */
export async function fetchOrphanImageAttachments(
  conversationId: string,
  messageId?: string,
): Promise<string[]> {
  const q = messageId ? `?messageId=${encodeURIComponent(messageId)}` : "";
  const res = await api.get<OrphanImageAttachmentsDTO>(
    `/conversations/${conversationId}/orphan-image-attachments${q}`,
  );
  return res.upload_ids;
}

// Bumped when an approval is submitted that records a conversation grant, so the
// AUTO-APPROVED strip refetches at approve time rather than waiting for the next
// stream-state toggle (the run is already mid-flight when the grant is made).
const [grantsRevision, setGrantsRevision] = createSignal(0);
export const conversationGrantsRevision = grantsRevision;

interface ApprovalGrantDTO {
  tool_name: string;
  // The backend also returns `expires_at`; the strip shows only the tool name, so it's
  // intentionally not mapped into the seam type.
}

/** The tools the operator allowed to auto-approve for the rest of this conversation. */
export async function fetchGrants(
  conversationId: string,
): Promise<ApprovalGrant[]> {
  const rows = await api.get<ApprovalGrantDTO[]>(
    `/conversations/${conversationId}/grants`,
  );
  return rows.map((r) => ({ toolName: r.tool_name }));
}

/** The agent's task list for a thread.
 *
 *  The list also arrives live on `plan.updated`, but a client opening or reloading a
 *  conversation has no stream to replay — this is how the panel starts from the truth
 *  instead of staying empty until the next mutation.
 */
export async function fetchPlan(conversationId: string): Promise<PlanItem[]> {
  return api.get<PlanItem[]>(`/conversations/${conversationId}/plan`);
}

/** The stream path for this thread's live agent browser, or null when it has none.
 *
 *  The `browser.live` event announces a session as the agent first touches a page, but a
 *  client that reloads (or opens the thread later) has no stream to replay and the
 *  session outlives the run that announced it — so the backend's session manager, not the
 *  transcript, is what the panel starts from.
 */
export async function fetchBrowserSession(
  conversationId: string,
): Promise<string | null> {
  const info = await api.get<{ active: boolean; url: string | null }>(
    `/browser/session/${conversationId}`,
  );
  return info.active ? info.url : null;
}

/** Revoke a conversation auto-approval — the next call to that tool asks again. */
export async function revokeGrant(
  conversationId: string,
  toolName: string,
): Promise<void> {
  await api.del(
    `/conversations/${conversationId}/grants/${encodeURIComponent(toolName)}`,
  );
}

/** This conversation's compaction state (its override + the resolved effective on/off) —
 *  folding older turns into a summary once the context window fills. The only reduction
 *  there is; per-tool-result digesting was removed. */
export async function fetchAutoCompactOverride(
  conversationId: string,
): Promise<CompactionState> {
  return api.get<CompactionState>(
    `/conversations/${conversationId}/auto-compact`,
  );
}

/** Force conversation compaction on/off for this chat (or `null` to inherit the global
 *  setting); returns the new state. */
export async function setAutoCompactOverride(
  conversationId: string,
  override: boolean | null,
): Promise<CompactionState> {
  return api.put<CompactionState>(
    `/conversations/${conversationId}/auto-compact`,
    { override },
  );
}

/* ── Streaming controller ─────────────────────────────────────────────────────
   Drives the live message list off a run's SSE stream. The public shape
   (messages, sending, send, resolveApproval) is the seam the screen renders. */

interface ChatCreatedDTO {
  run_id: string;
  conversation_id: string;
  /** Set when the send was queued into the conversation's already-live run
   *  (mid-run steering) instead of starting a new one. */
  queued_message_id?: string | null;
}

let counter = 0;
const nextId = (prefix: string) => `${prefix}-live-${++counter}`;

export interface ChatStreamOptions {
  /** Fired once when a brand-new conversation receives its backend id. */
  onConversationStarted?: (id: string) => void;
  /** Fired when a turn finishes (done or errored) — refresh the session list. */
  onTurnComplete?: () => void;
  /** Override the model this stream's turns run on, instead of the global picker
   *  selection. Used by the compare panes, which each own a per-pane model. */
  selection?: () => ModelSelection | null;
  /** Mark a freshly-created conversation as scratch (hidden from the sidebar
   *  listing). Used by compare panes — throwaway threads, not saved history. */
  ephemeral?: boolean;
  /** What kind of thread the *next new* conversation should be — an ordinary one, a
   *  research thread, or a code thread working in `projectId`'s git worktree. Read
   *  only when a send creates the conversation — the binding is immutable afterwards,
   *  and the backend owns it from then on. */
  mode?: () => SessionMode;
  projectId?: () => string | undefined;
  /** How far the model may go this turn — and from this turn onwards. Unlike the
   *  mode, sent on **every** send: the level is the operator's live control, so
   *  switching it mid-thread is a plain message rather than a separate call, and the
   *  backend persists whatever the last send named. */
  permission?: () => PermissionLevel;
  /** The loaded conversation's context-window state, seeded alongside its history
   *  so an existing thread shows window fullness before its next turn runs. */
  initialContext?: () => ContextUsage | null | undefined;
  /** The loaded conversation's cumulative readout, seeded the same way. The backend
   *  rebuilds it from the stored messages, so the line under the composer says the
   *  same thing after a reload as it did while the thread was live. */
  initialStats?: () => ConversationStats | null | undefined;
  /** The loaded conversation's in-flight run, if a turn is still streaming
   *  server-side. Seeds a reattach on a cold read (e.g. a page reload mid-stream)
   *  so the live answer continues instead of the thread rendering reply-less. */
  activeRun?: () => ActiveRun | null | undefined;
  /** The loaded conversation's workspace snapshots (git-style history), seeded
   *  alongside its messages so the viewport shows them before the next turn. */
  initialSnapshots?: () => ViewSnapshotRef[] | undefined;
}

export function createChatStream(
  initial: () => ChatMessage[] | undefined,
  key: () => string | null = () => null,
  options: ChatStreamOptions = {},
) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  // Conversation-level workspace snapshots (git-style history). Unlike versions/
  // live (which fold onto message blocks), snapshots are conversation-scoped, so
  // they live here beside the messages rather than in the transcript.
  const [snapshots, setSnapshots] = createSignal<ViewSnapshotRef[]>([]);
  // The thread's live agent browser, as a stream path — conversation-scoped like the
  // snapshots, and for a stronger reason: the browser session outlives the run that
  // opened it, so a message block (which replays with the transcript) would resurrect a
  // browser that has since been reaped.
  const [browserStream, setBrowserStream] = createSignal<string | null>(null);
  const [sending, setSending] = createSignal(false);
  // True when this room's last run ended in `run.error`; cleared when the next run
  // starts (in `driveRun`). The main room mirrors it to the global `runErrored` echo
  // so the favicon can flag a failed run — compare panes keep it local.
  const [errored, setErrored] = createSignal(false);
  // True when the live run's SSE transport exhausted its reconnect budget —
  // the run may still be alive server-side, but this client lost its
  // connection to it. Cleared when the next run/reattach starts (`driveRun`).
  // Mirrors `errored`'s pattern, but distinct: a detached turn isn't "over",
  // so the composer and the resume()/reattach paths must keep treating it as
  // in-flight rather than settled.
  const [detached, setDetached] = createSignal(false);
  // True while the room has a live, undecided approval — folded by `approval.required`
  // (both the generic approval card and the host-command terminal's pending phase) and
  // gated on `sending()` so it clears the moment the run stops being in flight, whether
  // by resolution (the approval/host-command block is filtered/re-phased out of
  // `messages` on submit — see `resolveApproval`/`resolveHostCommands`), a cancel, or the
  // run ending. A derived memo rather than its own set/clear pair: the blocks are already
  // the single source of truth for "is something still pending", so this only reads them.
  const awaitingApproval = createMemo(
    () =>
      sending() &&
      messages.some((m) =>
        m.blocks?.some(
          (b) =>
            (b.kind === "approval" && !b.approval.stale) ||
            (b.kind === "host_command" && b.command.phase === "pending"),
        ),
      ),
  );
  // A brand-new thread is auto-named during its first turn; this drives a "working"
  // throbber on the title from that turn's start until the name lands
  // (`conversation.titled`, which the reveal then animates) or the turn ends without
  // one. Backend-owned outcome — the frontend only reflects the in-flight window.
  const [titlePending, setTitlePending] = createSignal(false);
  // The latest run's context-window state, as derived by the backend. Null until
  // a run reports it against a known window (loaded history carries none), which
  // is when the context meter first appears.
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  // What the thread has cost — the composer's readout line. One signal, because the
  // backend sends one shape: the live `run.metrics` frame and the conversation load's
  // `stats` are the same payload, so a reload continues the same numbers rather than
  // blanking them. (This was three signals off one event; the counts and the token
  // counts were never separate facts.)
  const [stats, setStats] = createSignal<ConversationStats | null>(null);
  // The agent's task list for this thread. Conversation-level rather than a message
  // block: one list belongs to the thread and is rewritten in place as work proceeds,
  // so pinning it to the turn that happened to create it would strand it. `plan.updated`
  // carries the whole list, so applying an event is a replace, never a merge.
  const [plan, setPlan] = createSignal<PlanItem[]>([]);
  // Bumped on every `plan.updated`. Plain counter, not a signal: its only job is to let
  // an in-flight REST backfill notice the stream overtook it.
  let planRevision = 0;
  // True while a reattach (replay from a known run) is folding in — drives the
  // "RESYNCING…" affordance, distinct from a fresh turn's `sending`.
  const [reattaching, setReattaching] = createSignal(false);
  // Text of steering messages that were still queued when their run reached
  // terminal (cancel/error/timeout) — never delivered to the model. The screen
  // hands it back to the composer as a prefill so the operator's words aren't
  // lost; cleared once consumed.
  const [undeliveredDraft, setUndeliveredDraft] = createSignal<string | null>(
    null,
  );
  let controller: AbortController | null = null;
  // The run currently streaming, if any — needed to cancel it on the backend
  // (aborting the SSE alone leaves the run executing server-side).
  let activeRunId: string | null = null;
  // The assistant message events currently fold onto. Normally the placeholder
  // `driveRun` was started with, but a `message.injected` boundary closes that
  // bubble and retargets to a fresh one — mirroring how the persisted tree
  // splits a steered turn into segments around the injected user message.
  let foldTarget: string | null = null;
  // The highest event `seq` folded for the current run. Two purposes: (1) the
  // resume point a reattach replays *after* (avoids re-applying the head), and
  // (2) an idempotency guard in `foldEvent` so an overlapping old+new reader can
  // never double-apply an append delta. Events are seq ≥ 1, so 0 = nothing folded.
  let maxFoldedSeq = 0;
  // The last run a cold-read reattach was kicked off for, so the load effect fires
  // at most once per run even if the session resource re-emits the same value.
  let reattachedRunId: string | null = null;
  // Bumped whenever a drive is superseded (reattach aborts the prior reader, or a
  // thread switch tears it down). A driveRun whose generation is stale skips its
  // teardown so an aborted stalled reader can't clear the state — or refetch the
  // wrong thread — out from under the drive that replaced it.
  let driveGen = 0;
  // Set when the operator cancels the in-flight run, so the just-ended drive's
  // `adoptServerMeta` skips its reseat: a cancelled turn persists nothing, so the
  // backend history is *shorter* than the optimistic store, and reseating to it
  // would discard the whole in-flight turn (and, on a brand-new conversation with
  // no prior turns, blank the chat entirely). Reset at the start of each drive.
  let cancelled = false;
  // The conversation this stream is currently bound to (tracked separately from
  // the screen's `key`, which only updates once a new thread is persisted).
  let activeConversationId: string | null = key();

  // Re-seed when the conversation changes. Guard: don't wipe a live thread while
  // its server history is still loading (the just-created thread re-loads with
  // identical content, so skipping avoids an empty flash).
  const INIT = Symbol("init");
  let lastKey: string | null | typeof INIT = INIT;
  let lastSource: ChatMessage[] | undefined | typeof INIT = INIT;
  createEffect(() => {
    const k = key();
    const source = initial();
    if (k === lastKey && source === lastSource) return;
    // Record the transition before any early return below, or the bookkeeping
    // goes stale: skipping these on the authoritative-store guard left `lastKey`
    // pinned at its pre-adoption value, so a later transition back to that value
    // (e.g. compare's teardown reverting the key to null) read as "no change"
    // and the transcript never cleared.
    lastKey = k;
    lastSource = source;
    // The live store is authoritative for the thread we're already on: never let
    // a (re)fetch of its server history clobber it. This keeps a freshly-created
    // thread's streamed messages — including live-only fields the history
    // projection doesn't carry (preview, artifacts, runId) — when it adopts its
    // backend id, and avoids an empty flash while that history loads.
    if (k === activeConversationId && messages.length > 0) return;
    controller?.abort();
    controller = null;
    driveGen++; // supersede any in-flight drive so its finally skips teardown
    setSending(false);
    setReattaching(false);
    setDetached(false);
    // A new thread starts a fresh event sequence; drop the prior run's fold/resume
    // bookkeeping so its seqs don't suppress the next run's events.
    maxFoldedSeq = 0;
    activeRunId = null;
    foldTarget = null;
    // Forget which run we've already reattached-to: leaving this thread (still
    // detached/mid-stream) and returning later must let the cold-reattach effect
    // fire again for the same run id, rather than permanently ignoring a run it
    // saw once, in some earlier visit, before this stream instance existed.
    reattachedRunId = null;
    activeConversationId = k;
    // A null key is a new, unsaved conversation: it has no persisted history, so
    // the only `source` here is the seam resource's *retained* value from the
    // thread we just left (Solid keeps a resource's last value once its id goes
    // null). Seeding from it would keep a just-deleted thread's messages on
    // screen, so a null key always starts empty.
    const seed = k === null ? [] : source ? source.slice() : [];
    setMessages(reconcile(seed));
    // Seed the meter from the loaded thread's reconstructed state (null for a new
    // conversation, or one whose usage/window couldn't be determined).
    setUsage(k === null ? null : (options.initialContext?.() ?? null));
    // Seeded from the loaded thread, not cleared: the backend rebuilds the readout
    // from the stored messages, so an existing conversation reports what it has spent
    // before its next turn runs rather than starting the line blank.
    setStats(k === null ? null : (options.initialStats?.() ?? null));
    // Seed the git-style snapshot history from the loaded thread (empty for a new
    // conversation); the live `view.snapshot` event appends to it from here.
    setSnapshots(k === null ? [] : (options.initialSnapshots?.() ?? []));
    // A live browser belongs to the thread, not to the client — so a switch clears the
    // previous thread's and asks the backend whether *this* one has one.
    setBrowserStream(null);
    // The plan is owned by the backend and survives reloads, so a thread switch clears
    // the old one and refetches rather than carrying the previous thread's list over.
    setPlan([]);
    if (k !== null) {
      const requested = k;
      // Snapshot the live-update counter: opening a thread whose run is mid-turn races
      // the backfill against `plan.updated`, and the fetch answers with pre-mutation
      // state. Without this the slower fetch wins and the panel goes stale until the
      // next mutation — which may never come.
      const seenAtRequest = planRevision;
      void fetchPlan(requested)
        .then((items) => {
          // Drop it if the operator has since left the thread, or the stream already
          // said something newer.
          if (key() === requested && planRevision === seenAtRequest)
            setPlan(items);
        })
        .catch(() => {
          // The panel is an aid, not the transcript — a failed backfill leaves it
          // empty and the next `plan.updated` fills it in.
        });
      void fetchBrowserSession(requested)
        .then((path) => {
          // Only if the operator is still on this thread, and the stream hasn't already
          // announced a session (which would be newer than this answer).
          if (key() === requested && browserStream() === null)
            setBrowserStream(path);
        })
        .catch(() => {
          // Browser control may not be wired at all; no panel is the right answer.
        });
    }
  });

  function patchById(id: string, fn: (m: ChatMessage) => void): void {
    const i = messages.findIndex((m) => m.id === id);
    if (i < 0) return;
    setMessages(produce((m) => fn(m[i])));
  }

  /** Append a streamed delta onto the trailing block of `kind`, starting a new
   *  block whenever the kind changes. This is what turns the flat delta stream
   *  into an ordered, interleaved sequence — and what gives a turn *multiple*
   *  thinking blocks (each resumption after a tool/text starts a fresh one). */
  function appendDelta(
    m: ChatMessage,
    kind: "thinking" | "text",
    text: string,
  ): void {
    const blocks = m.blocks ?? (m.blocks = []);
    const last = blocks[blocks.length - 1];
    if (last && last.kind === kind) last.text += text;
    else blocks.push({ kind, id: nextId(kind), text });
  }

  function findTool(m: ChatMessage, toolCallId: string): ToolBlock | undefined {
    return m.blocks?.find(
      (b): b is ToolBlock => b.kind === "tool" && b.tool.id === toolCallId,
    );
  }

  /** The review row for one call, keyed by tool_call_id — `review.started` opens it and
   *  `review.completed` fills in the verdict on the same block, so the row the operator
   *  saw appear is the row that ends up carrying the answer. */
  function findReview(
    m: ChatMessage,
    toolCallId: string,
  ): ReviewBlock | undefined {
    return m.blocks?.find(
      (b): b is ReviewBlock =>
        b.kind === "review" && b.review.toolCallId === toolCallId,
    );
  }

  /** Upsert a host-command *block*, keyed by tool_call_id. The host call's
   *  `tool.started`, `approval.required`, and `tool.completed` events all land
   *  here, each filling in the part it carries onto the same terminal block. */
  function upsertHost(
    m: ChatMessage,
    toolCallId: string,
    patch: Partial<HostCommand>,
  ): void {
    const existing = m.blocks?.find(
      (b): b is HostCommandBlock =>
        b.kind === "host_command" && b.command.toolCallId === toolCallId,
    );
    if (existing) Object.assign(existing.command, patch);
    else
      (m.blocks ?? (m.blocks = [])).push({
        kind: "host_command",
        id: `host-${toolCallId}`,
        command: { toolCallId, command: "", phase: "pending", ...patch },
      });
  }

  function foldEvent(anchorId: string, ev: RunEvent): void {
    // Idempotency: `seq` is monotonic per run, so an event at or below the high-
    // water mark was already folded (a reattach replay overlapping a still-live
    // reader). Skipping it stops a re-applied `answer.delta` from doubling text.
    if (ev.seq <= maxFoldedSeq) return;
    maxFoldedSeq = ev.seq;
    // Events land on the current fold target: the drive's placeholder until a
    // `message.injected` boundary retargets to a fresh assistant bubble.
    const assistantId = foldTarget ?? anchorId;
    switch (ev.type) {
      case "thinking.delta":
        patchById(assistantId, (m) => appendDelta(m, "thinking", ev.text));
        break;
      case "answer.delta":
        patchById(assistantId, (m) => appendDelta(m, "text", ev.text));
        break;
      case "tool.started":
        // Host commands are terminals, not generic tool cards. (tool.started
        // fires before approval.required, so this seeds the pending terminal.)
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, {
              command:
                typeof ev.args.command === "string" ? ev.args.command : "",
              explanation:
                typeof ev.args.explanation === "string"
                  ? ev.args.explanation
                  : undefined,
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "tool",
            id: `tool-${ev.tool_call_id}`,
            tool: {
              id: ev.tool_call_id,
              name: ev.name,
              args: formatArgs(ev.args),
              detail: describeToolArgs(ev.name, ev.args),
              status: "running",
            },
          });
        });
        break;
      case "tool.progress":
        // A running tool's status note (e.g. the sandbox spinning up). Folds onto
        // the generic tool card; host commands have their own terminal lifecycle.
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) b.tool.progress = ev.partial ?? undefined;
        });
        break;
      case "tool.completed":
        if (ev.name === HOST_COMMAND_TOOL) {
          const r = parseHostResult(ev.result);
          if (r) {
            patchById(assistantId, (m) =>
              upsertHost(m, ev.tool_call_id, {
                phase: hostPhaseFromResult(r),
                exitCode: r.exit_code,
                stdout: r.stdout,
                stderr: r.stderr,
                timedOut: r.timed_out,
                error: r.error,
              }),
            );
          }
          break;
        }
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) {
            b.tool.status = "ok";
            b.tool.result = stringifyResult(ev.result);
            b.tool.outcome = describeToolResult(ev.name, ev.result);
            b.tool.progress = undefined; // the run is over — drop the spin-up note
            b.tool.images = toolImages(ev.images);
          }
        });
        break;
      case "tool.failed":
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, {
              phase: "error",
              error: ev.error,
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) {
            b.tool.status = "error";
            b.tool.error = ev.error;
            b.tool.progress = undefined; // the run is over — drop the spin-up note
          }
        });
        break;
      case "context.injected":
        // A block the chassis put in front of the model. It lands on the rail in the
        // order it happened — which is ahead of the work it shaped, since the turn's
        // context is assembled before the model sees any of it. Keyed by `seq` because
        // the same contributor can legitimately inject twice in one turn (a plan that
        // grew a task between steps is a new injection, not a repeat), and `seq` is the
        // only identifier on the wire that is unique per event and stable across a
        // replay.
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "context",
            id: `ctx-${ev.seq}`,
            injection: {
              contributor: ev.contributor,
              placement: ev.placement,
              tokens: ev.tokens,
              text: ev.text,
              truncated: ev.truncated,
            },
          });
        });
        break;
      case "review.started":
        // The chassis is about to answer for the operator. The row opens now rather than
        // on the verdict, so a review that costs a model call reads as work in flight —
        // and so it lands ahead of the tool row it judges, which is where it belongs.
        patchById(assistantId, (m) => {
          if (findReview(m, ev.tool_call_id)) return;
          (m.blocks ?? (m.blocks = [])).push({
            kind: "review",
            id: `review-${ev.tool_call_id}`,
            review: {
              toolCallId: ev.tool_call_id,
              name: ev.name,
              summary: ev.summary,
            },
          });
        });
        break;
      case "review.completed":
        patchById(assistantId, (m) => {
          const b = findReview(m, ev.tool_call_id);
          if (!b) return;
          b.review.decision = ev.decision;
          b.review.stage = ev.stage;
          b.review.reason = ev.reason;
          // Null on the wire means the model stage never ran — the deterministic judge
          // cleared it, or there was nothing to review with. Undefined here so the card
          // renders the axes only when there are axes.
          b.review.risk = ev.risk ?? undefined;
          b.review.authorization = ev.authorization ?? undefined;
          b.review.correctness = ev.correctness ?? undefined;
        });
        break;
      case "plan.updated":
        // Whole-list replace, not a merge: the event is full state, which is what makes
        // it idempotent when the stream is replayed from an earlier seq on reconnect.
        planRevision += 1;
        setPlan(ev.items);
        break;
      case "approval.required": {
        // `args` is typed as always-present, but it arrives as untrusted JSON off
        // the wire — default it once here, in the mapper, so no consumer of the
        // stored block has to guard a `Object.keys(args)` or an `args.command`.
        const args: Record<string, unknown> = ev.args ?? {};
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, {
              command: typeof args.command === "string" ? args.command : "",
              explanation: ev.explanation ?? undefined,
              phase: "pending",
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "approval",
            id: `approval-${ev.tool_call_id}`,
            approval: {
              toolCallId: ev.tool_call_id,
              name: ev.name,
              args,
              summary: ev.summary,
              explanation: ev.explanation ?? undefined,
            },
          });
        });
        break;
      }
      case "view.live": {
        // One live head per *conversation*, not per turn: clear any prior live
        // block (it may sit on an earlier turn) before marking this turn's, so a
        // replaced or stopped server never lingers as a stale LIVE head once the
        // viewport aggregates view items across the whole transcript.
        const live = { url: ev.url, title: ev.title ?? undefined };
        setMessages(
          produce((list) => {
            for (const m of list)
              if (m.blocks)
                m.blocks = m.blocks.filter((b) => b.kind !== "view_live");
            const m = list.find((x) => x.id === assistantId);
            if (m)
              (m.blocks ?? (m.blocks = [])).push({
                kind: "view_live",
                id: nextId("view-live"),
                live,
              });
          }),
        );
        break;
      }
      case "view.live.stopped":
        // The live head is conversation-scoped and close usually arrives a turn or
        // more after it started — drop it wherever it lives, not just on this run.
        setMessages(
          produce((list) => {
            for (const m of list)
              if (m.blocks)
                m.blocks = m.blocks.filter((b) => b.kind !== "view_live");
          }),
        );
        break;
      case "browser.live":
        // Conversation-scoped, not a message block: the session outlives this run, and a
        // block would replay a long-reaped browser on the next cold load. There is no
        // stopped counterpart — the panel's own socket carries the end (see
        // `browserLive.ts`), because a reap happens between turns with no stream to
        // carry an event.
        setBrowserStream(ev.url);
        break;
      case "view.snapshot": {
        // A version minted by `show`: append to the conversation-scoped version list
        // (the panel), deduped since a reattach replay can re-deliver the event.
        const ref = toViewSnapshotRef(ev);
        setSnapshots((prev) =>
          prev.some((s) => s.snapshotId === ref.snapshotId)
            ? prev
            : [...prev, ref],
        );
        // Fold an inline transcript chip only for a *static* preview (a `show(file=…)`).
        // A live/auto version (served head) is already marked by its `view_live` chip,
        // so a second chip for the same action would just be visual duplication.
        if (ref.preview) {
          const chip = toVersionChipBlock(assistantId, {
            snapshotId: ref.snapshotId,
            title: ref.title,
            previewKind: ref.preview.kind,
          });
          patchById(assistantId, (m) => {
            const blocks = m.blocks ?? (m.blocks = []);
            if (!blocks.some((b) => b.id === chip.id)) blocks.push(chip);
          });
        }
        break;
      }
      case "message.queued":
        // A steering message the backend accepted into this run. Usually it tags
        // the optimistic bubble `send` already pushed (matched by text, first
        // untagged wins so duplicate texts pair off in order); on a reattach
        // replay there is no optimistic bubble, so rebuild it from the event.
        setMessages(
          produce((list) => {
            if (list.some((m) => m.queuedMessageId === ev.message_id)) return;
            const untagged = list.find(
              (m) =>
                m.queuedPending && !m.queuedMessageId && m.content === ev.text,
            );
            if (untagged) untagged.queuedMessageId = ev.message_id;
            else
              list.push({
                id: nextId("u"),
                role: "user",
                content: ev.text,
                queuedPending: true,
                queuedMessageId: ev.message_id,
                createdAt: ev.ts,
              });
          }),
        );
        break;
      case "message.edited":
        // The operator rewrote a still-pending bubble. Usually `editQueued`
        // already applied the text optimistically-on-success; this fold makes a
        // reattach replay (and any second tab) converge on the same content. An
        // already-injected message is part of the turn and never changes.
        setMessages(
          produce((list) => {
            const bubble = list.find(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (bubble) bubble.content = ev.text;
          }),
        );
        break;
      case "message.withdrawn":
        // Only a still-pending bubble is removable — an already-injected message
        // is part of the turn and must never vanish from the transcript.
        setMessages(
          produce((list) => {
            const i = list.findIndex(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (i >= 0) list.splice(i, 1);
          }),
        );
        break;
      case "message.injected":
        // The queued message reached the model: promote its bubble to a normal
        // user turn and split the assistant flow around it, mirroring how the
        // backend persists the steered turn (…assistant segment, user message,
        // next assistant segment…) so the live transcript and a reload agree.
        setMessages(
          produce((list) => {
            const qi = list.findIndex(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (qi < 0) return;
            const [bubble] = list.splice(qi, 1);
            bubble.queuedPending = false;
            const target = list.find((m) => m.id === assistantId);
            const targetIsFresh =
              target && !target.blocks?.length && !target.content;
            if (targetIsFresh && list[list.length - 1] === target) {
              // A batch of injections at one boundary shares one fresh segment:
              // slot this message before the placeholder a prior injection opened.
              list.splice(list.length - 1, 0, bubble);
            } else {
              if (target) target.streaming = false;
              list.push(bubble);
              const fresh: ChatMessage = {
                id: nextId("a"),
                role: "assistant",
                model: target?.model,
                content: "",
                blocks: [],
                streaming: true,
                runId: activeRunId ?? undefined,
                createdAt: new Date().toISOString(),
              };
              list.push(fresh);
              foldTarget = fresh.id;
            }
          }),
        );
        break;
      case "conversation.compacted": {
        // Conversation-level, like the title above — but it *is* a message, so it goes
        // into the list. Placed after the turn the backend named rather than appended:
        // a divider at the bottom would claim to have folded the turns it kept, and a
        // reload (which places it chronologically) would then disagree with the live view.
        const divider: ChatMessage = {
          id: ev.message_id,
          role: "compaction",
          content: ev.summary,
          createdAt: ev.ts,
          foldedMessages: ev.messages_compacted,
          tokensBefore: ev.tokens_before ?? undefined,
          tokensAfter: ev.tokens_after ?? undefined,
        };
        // Idempotent on `message_id`: a reattach replays the run's whole buffer
        // (`fromSeq: 0`) over a transcript that was cold-loaded *with* this divider
        // already in it, so an unguarded splice would seat a second identical rule —
        // and re-announce a fold that happened minutes ago.
        let inserted = false;
        setMessages(
          produce((list) => {
            if (list.some((m) => m.id === divider.id)) return;
            inserted = true;
            const at = ev.after_message_id
              ? list.findIndex((m) => m.id === ev.after_message_id)
              : -1;
            if (at >= 0) list.splice(at + 1, 0, divider);
            else list.push(divider);
          }),
        );
        // A fold that lands mid-answer scrolls past unseen — and it changes what the
        // model can still see, which is not something to discover later by reading
        // back. The divider is the durable record; this is the notification.
        // `messages_compacted` counts messages, not exchanges — say messages.
        if (inserted)
          toast.info(
            ev.messages_compacted > 0
              ? `Context compacted — ${ev.messages_compacted} earlier ${ev.messages_compacted === 1 ? "message is" : "messages are"} now a summary for the model.`
              : "Context compacted — earlier messages are now a summary for the model.",
          );
        break;
      }
      case "conversation.titled":
        // Conversation-level, not message-level: hand it to the typewriter reveal
        // rather than folding onto the assistant message. The throbber clears in the
        // run's `finally` (when the new conversation's id is adopted and the reveal
        // can actually render), not here — clearing now would flash the bare title
        // for the beat before that.
        revealTitle(ev.conversation_id, ev.title);
        break;
      case "conversation.linked":
        // The turn spawned a thread of its own. Pull the list now rather than at
        // the end of the turn: the new thread is already running, and a session
        // that exists but isn't listed for another few minutes reads as work that
        // went nowhere. The toast is the account of *why* a row appeared.
        refreshSessions();
        toast.info(
          ev.title
            ? `Research thread started — ${ev.title}`
            : "Research thread started.",
        );
        break;
      case "run.error":
        toast.error(ev.message || "The run failed.");
        patchById(assistantId, (m) => (m.streaming = false));
        setErrored(true);
        break;
      case "run.metrics":
        // The backend derives the window's fullness; the meter just renders it.
        // Authoritative either way: a null context (this turn ran on a windowless
        // model, or reported no usage) clears a stale reading rather than keeping it.
        setUsage(ev.context);
        setStats(toStats(ev));
        break;
      case "citation.added":
        patchById(assistantId, (m) => {
          const citations = m.citations ?? (m.citations = []);
          if (!citations.some((c) => c.url === ev.url))
            citations.push({ url: ev.url, title: ev.title ?? undefined });
        });
        break;
      case "limit.notice":
        // A bound on the turn. "verify" is a transient "re-attempting…" progress note,
        // not a stop — leave it silent. The rest stopped the run, so surface why: the
        // "context" message carries the model's window size, so the operator knows the
        // conversation hit the ceiling and can start a new chat rather than wonder.
        if (ev.limit !== "verify") toast.error(ev.message);
        break;
      case "run.ended":
        // A blocked outcome is a real stopping point, not a normal finish —
        // leave a persistent marker on the turn (the limit.notice toast alone
        // vanishes, and a reload would otherwise show a turn that just stops).
        if (ev.outcome === "blocked")
          patchById(assistantId, (m) => {
            m.blocked = true;
            m.blockedDetail = ev.detail ?? undefined;
          });
        break;
      // run.started / step.*: no store change
    }
  }

  /** Drop any still-pending steering bubbles and hand their text back to the
   *  composer (`undeliveredDraft`). Idempotent — a no-op when nothing is
   *  pending — so the drive teardown and `cancel` can both call it safely. */
  function restoreUndelivered(): void {
    const leftovers = messages.filter((m) => m.queuedPending);
    if (leftovers.length === 0) return;
    setMessages(reconcile(messages.filter((m) => !m.queuedPending)));
    const text = leftovers.map((m) => m.content).join("\n");
    setUndeliveredDraft((prev) => (prev ? `${prev}\n${text}` : text));
    toast.warn(
      "Your queued message wasn't delivered — it's back in the input.",
    );
  }

  /** Drive a started run to completion: open the SSE, fold every event onto the
   *  given assistant message, and on end clear streaming/sending, fire the
   *  lifecycle callbacks, and refresh the session list. Shared by `send` and the
   *  branching ops (regenerate/edit) so the run tail lives in one place.
   *  `wasNew` reports a freshly-created conversation so its id can be adopted. */
  async function driveRun(
    runId: string,
    assistantId: string,
    wasNew = false,
    fromSeq?: number,
    onConnected?: () => void,
  ): Promise<void> {
    const myGen = ++driveGen;
    cancelled = false; // a fresh run clears any prior cancel signal
    activeRunId = runId;
    setErrored(false); // a fresh run supersedes any prior failure
    setDetached(false); // a fresh run/reattach supersedes any prior detach
    // Re-anchor the fold high-water mark to this run's sequence. Each run owns a
    // fresh event stream whose seq restarts at 1, so a new turn (fromSeq omitted →
    // 0) must drop the *previous* run's mark — otherwise its early events (seq ≤
    // that stale mark) are suppressed in `foldEvent` and the answer streams in
    // blank until the counter catches up (or never, if this turn is shorter). A
    // reattach passes `fromSeq` = the last seq it folded, replaying only the gap.
    maxFoldedSeq = fromSeq ?? 0;
    // Events start folding onto the placeholder; a `message.injected` boundary
    // retargets this as the run's segments split.
    foldTarget = assistantId;
    patchById(assistantId, (m) => {
      m.runId = runId;
      m.detached = false; // a fresh drive/reattach supersedes any prior detach
    });
    let connected = false;
    let detachedNow = false;
    try {
      controller = new AbortController();
      await streamRun(runId, {
        signal: controller.signal,
        fromSeq,
        onEvent: (ev) => {
          // First event = the transport is live again; let a reattach drop its
          // "RESYNCING…" badge here, so it shows only across the reconnect latency.
          // It's also the queued→streaming transition: the backend only starts
          // emitting once the run actually clears the concurrency semaphore, so
          // the first frame (of any kind) is what tells us it's no longer queued.
          if (!connected) {
            connected = true;
            patchById(assistantId, (m) => (m.queued = false));
            onConnected?.();
          }
          foldEvent(assistantId, ev);
        },
      });
    } catch (err) {
      if (myGen !== driveGen) {
        // superseded — nothing to surface
      } else if (err instanceof StreamDetachedError) {
        // The transport gave up reconnecting, but the run may still be alive
        // server-side: don't treat the turn as ended. Leave it in a distinct
        // "detached" state (not streaming, not settled) with a re-attach
        // affordance, and keep `activeRunId`/`sending` as-is so the composer
        // stays guarded and the visibility/online resume listeners still see
        // an in-flight run to reattach to.
        detachedNow = true;
        setDetached(true);
        patchById(foldTarget ?? assistantId, (m) => {
          m.streaming = false;
          m.queued = false;
          m.detached = true;
        });
        toast.error(
          "Connection lost. The response may still be running — reconnect to continue.",
        );
      } else {
        toast.error(
          (err as { detail?: string })?.detail ??
            "Unable to reach the assistant.",
        );
      }
    } finally {
      // Skip teardown when superseded by a reattach/thread-switch (that drive
      // owns the state now, and clearing it here would race it) or when this
      // drive ended detached — the run isn't actually over, so `activeRunId`/
      // `sending` must keep reporting it as in-flight until it's re-attached,
      // cancelled, or superseded.
      if (myGen === driveGen && !detachedNow) {
        activeRunId = null;
        patchById(foldTarget ?? assistantId, (m) => {
          m.streaming = false;
          m.detached = false; // the turn is genuinely over — clear any stale banner
          m.queued = false; // defensive: covers a resolve with no frames ever folded
        });
        // Steering messages the run never consumed (it was cancelled/errored/
        // timed out before their boundary): hand the text back to the composer
        // rather than silently dropping the operator's words.
        restoreUndelivered();
        setSending(false);
        setTitlePending(false); // turn ended — clear even if no title landed
        if (wasNew && activeConversationId) {
          options.onConversationStarted?.(activeConversationId);
        }
        options.onTurnComplete?.();
        // Adopt the backend's authoritative ids + version metadata for the turn
        // just recorded — without this the live message keeps its client id and a
        // stale version count, so the ‹k/n› cycler never appears and a later
        // regenerate/edit/delete/pin would address an id the backend doesn't know.
        await adoptServerMeta();
      }
    }
  }

  /** Reattach to a run that's already streaming (or just finished) and fold what
   *  we missed, then continue live. Two callers:
   *  - resume after a stalled/dropped transport (a backgrounded tab): the
   *    assistant message still exists, so replay from `fromSeq` = the last seq we
   *    folded — only the tail re-applies (the seq guard drops the overlap).
   *  - a cold read mid-stream (page reload): no assistant turn exists yet, so seed
   *    an empty one bound to the run and replay the whole buffer (`fromSeq` 0).
   *  Reuses `driveRun`, so the shared finally clears streaming/sending and
   *  reconciles the persisted turn once the run ends. */
  async function reattachRun(
    runId: string,
    opts: { fromSeq: number },
  ): Promise<void> {
    // Abort a stalled/old reader first so it can't keep folding beside the new one
    // (its drive is superseded by the generation bump inside the next driveRun).
    controller?.abort();
    controller = null;
    // The *last* matching turn: a steered run splits into several assistant
    // segments sharing one runId, and only the newest is the live one.
    let assistantId = messages.findLast(
      (m) => m.runId === runId && m.role === "assistant",
    )?.id;
    const seeded = assistantId === undefined;
    if (assistantId === undefined) {
      assistantId = nextId("a");
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        blocks: [],
        streaming: true,
        runId,
        createdAt: new Date().toISOString(),
      };
      setMessages(produce((m) => m.push(assistantMsg)));
    } else {
      patchById(assistantId, (m) => {
        m.streaming = true;
        m.detached = false; // re-attaching supersedes the "connection lost" banner
      });
    }
    // `driveRun` re-anchors `maxFoldedSeq` to the `fromSeq` passed below, so the
    // resume replays only the gap after the last folded event.
    setSending(true);
    setReattaching(true);
    try {
      // Clears RESYNCING on the first folded event; the finally is the safety net
      // for a reattach that never connects (e.g. an immediate 404).
      await driveRun(runId, assistantId, false, opts.fromSeq, () =>
        setReattaching(false),
      );
    } finally {
      setReattaching(false);
    }
    // A freshly-seeded turn that folded nothing means the run was gone (evicted, or
    // lost to a server restart): fall back to the persisted thread so a finished
    // answer still shows rather than a blank assistant turn. Skip this when the
    // attempt itself ended detached (reconnect budget exhausted, not a 404/empty
    // buffer) — the run may still be alive, so reseating from the (possibly
    // reply-less) persisted detail here would discard the re-attach affordance
    // for no reason; leave the seed detached and let the operator/resume retry.
    if (
      !detached() &&
      seeded &&
      maxFoldedSeq === opts.fromSeq &&
      activeConversationId !== null
    ) {
      try {
        reseatFromDetail(
          await api.get<ConversationDetailDTO>(
            `/conversations/${activeConversationId}`,
          ),
        );
      } catch {
        // Leave the seed; the next navigation/refresh reconciles it.
      }
    }
  }

  /** Reconcile the live store with the backend's projected active path after a
   *  turn: adopt each turn's real node id + version index/count + pin by position
   *  (the store mirrors the same active path), leaving live-only fields the cold
   *  projection doesn't carry — `preview`, `runId` — untouched. A length mismatch
   *  (e.g. a turn that produced no persisted answer) falls back to a full reseat.
   *  Best-effort: a failed read leaves the optimistic store in place. */
  async function adoptServerMeta(): Promise<void> {
    if (activeConversationId === null) return;
    const convAtStart = activeConversationId;
    const lenAtStart = messages.length;
    let detail: ConversationDetailDTO;
    try {
      detail = await api.get<ConversationDetailDTO>(
        `/conversations/${convAtStart}`,
      );
    } catch {
      return;
    }
    // Bail if the store moved under us while the read was in flight: the operator
    // started another turn (length changed — the composer re-enabled the instant
    // streaming stopped) or switched threads. Reconciling now would reseat over the
    // new turn's optimistic messages and freeze its stream; that turn reconciles
    // itself when it completes.
    if (activeConversationId !== convAtStart || messages.length !== lenAtStart)
      return;
    const server = detail.messages;
    if (server.length !== messages.length) {
      // A shorter backend history normally means a turn produced no persisted
      // answer, so reseat to drop the optimistic turn. But a *cancelled* turn also
      // persists nothing — there reseating would discard the in-flight turn the
      // operator chose to keep (and blank a brand-new chat), so leave the store as
      // is; the next completed turn reconciles it.
      if (!cancelled) reseatFromDetail(detail);
      return;
    }
    setMessages(
      produce((list) => {
        for (let i = 0; i < list.length; i++) {
          list[i].id = server[i].id;
          list[i].versionIndex = server[i].version_index;
          list[i].versionCount = server[i].version_count;
          list[i].pinned = server[i].pinned;
          // The store owns the stop marker (a continue retires it), so take its
          // word here too — otherwise a turn cleared server-side stays warned
          // locally until a full reseat.
          list[i].blocked = server[i].blocked_reason != null;
          list[i].blockedDetail = server[i].blocked_reason ?? undefined;
        }
      }),
    );
  }

  /** After a 409 (the backend already has a run active on this conversation —
   *  a parallel submit, a stale UI, or a second tab/device) look up the
   *  conversation's current active run and reattach to it, so the turn that's
   *  actually in flight becomes visible instead of silently going nowhere.
   *  Best-effort: a failed lookup just leaves the composer free to retry. */
  async function reattachToLiveRun(conversationId: string): Promise<void> {
    try {
      const detail = await api.get<ConversationDetailDTO>(
        `/conversations/${conversationId}`,
      );
      // Bail if the operator navigated to a different thread while the read was
      // in flight — reattachRun's abort+seed-push would otherwise contaminate
      // whatever conversation is live now with this one's run.
      if (activeConversationId !== conversationId) return;
      const ar = toActiveRun(detail.active_run);
      if (ar) await reattachRun(ar.id, { fromSeq: 0 });
    } catch {
      // Best effort — the operator can retry manually.
    }
  }

  /** After a submitted approval/host-command decision 409s (the run had already
   *  resumed elsewhere — a second tab, a retried request — by the time this one
   *  landed), the pending card's decision is moot. Refetch so the transcript
   *  reconciles with whatever the winning decision actually did, re-attaching to
   *  the run if it's still in flight. Unlike `reattachToLiveRun`, this always
   *  reseats — the winning decision may have already finished the run entirely,
   *  not just still be running. Best-effort: a failed refetch leaves the caller's
   *  stale marker as the only signal, but never re-throws into an unhandled turn. */
  async function reconcileStaleDecision(): Promise<void> {
    if (activeConversationId === null) return;
    const convAtStart = activeConversationId;
    try {
      const detail = await api.get<ConversationDetailDTO>(
        `/conversations/${convAtStart}`,
      );
      // Bail if the operator switched threads while the read was in flight — a
      // different thread is live now, so this stale decision's conversation
      // must not overwrite its store.
      if (activeConversationId !== convAtStart) return;
      reseatFromDetail(detail);
      const ar = toActiveRun(detail.active_run);
      if (ar) await reattachRun(ar.id, { fromSeq: 0 });
    } catch {
      // Best effort — the stale marker set by the caller still holds.
    }
  }

  /** Send while a run is live: the backend queues the message into that run
   *  (injected at its next boundary) — or, if the run ended in the meantime,
   *  starts a fresh turn; the response tells us which, so this client never
   *  picks. The optimistic bubble renders QUEUED until `message.injected`
   *  promotes it (or a withdraw/terminal removes it). */
  async function sendWhileStreaming(text: string): Promise<void> {
    if (activeConversationId === null) {
      // The first turn's POST hasn't resolved yet, so there's no conversation to
      // queue against. The composer already cleared itself — hand the text back
      // rather than dropping it.
      setUndeliveredDraft((prev) => (prev ? `${prev}\n${text}` : text));
      return;
    }
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
      queuedPending: true,
    };
    setMessages(produce((m) => m.push(userMsg)));
    let created: ChatCreatedDTO;
    try {
      created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId,
      });
    } catch (err) {
      // Not accepted (a regenerate/edit holds the claim, or transport failed):
      // roll the bubble back so the transcript only shows what the backend has.
      setMessages(reconcile(messages.filter((m) => m.id !== userMsg.id)));
      toast.error(
        isApiError(err) && err.status === 409
          ? "Can't queue this message right now — try again in a moment."
          : ((err as { detail?: string })?.detail ??
              "Unable to reach the assistant."),
      );
      return;
    }
    if (created.queued_message_id) {
      // Queued into the live run. The `message.queued` fold may have already
      // tagged the bubble via the open stream; this is the fallback tag.
      patchById(userMsg.id, (m) => {
        if (!m.queuedMessageId) m.queuedMessageId = created.queued_message_id!;
      });
      return;
    }
    // The run went terminal just before the POST landed: the backend started a
    // fresh run for this message instead. Promote the bubble to a normal turn
    // and drive the new run like any other send.
    patchById(userMsg.id, (m) => (m.queuedPending = false));
    const assistantId = nextId("a");
    setMessages(
      produce((m) =>
        m.push({
          id: assistantId,
          role: "assistant",
          model: (options.selection?.() ?? effectiveSelection())?.model,
          content: "",
          blocks: [],
          streaming: true,
          queued: true,
          createdAt: new Date().toISOString(),
        }),
      ),
    );
    setSending(true);
    activeConversationId = created.conversation_id;
    await driveRun(created.run_id, assistantId, false);
  }

  async function send(
    text: string,
    attachmentIds: string[] = [],
    /** Set only by `continueTurn`: the branch node id of the stopped turn this
     *  send resumes, so the backend retires that turn's stop marker for good. */
    continuesMessageId?: string,
  ): Promise<void> {
    // A turn needs either prompt text or at least one attachment to send.
    if (!text.trim() && attachmentIds.length === 0) return;
    if (sending()) {
      // Mid-run steering is text-only — an attachment can't ride an existing
      // run's request (and the composer disables attach while streaming).
      if (attachmentIds.length > 0) {
        toast.error(
          "Attachments can't be added while a response is in progress.",
        );
        return;
      }
      if (!text.trim()) return;
      await sendWhileStreaming(text);
      return;
    }
    setSending(true);

    const wasNew = activeConversationId === null;
    // A fresh, non-ephemeral thread gets auto-named during this turn; show the
    // working throbber on the title until it lands. Ephemeral threads aren't titled.
    if (wasNew && !options.ephemeral) setTitlePending(true);
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
      attachmentIds: attachmentIds.length ? attachmentIds : undefined,
    };
    // `override` is a genuine per-instance model (the compare panes); the default
    // path sends none, so the backend resolves the stored `main` binding — the same
    // source research/tasks/titling resolve. `selection` is only the display label.
    const override = options.selection?.();
    const selection = override ?? effectiveSelection();
    const assistantId = nextId("a");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      model: selection?.model,
      content: "",
      blocks: [],
      streaming: true,
      queued: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(produce((m) => m.push(userMsg, assistantMsg)));

    let created: ChatCreatedDTO;
    try {
      created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId ?? undefined,
        endpoint_id: override?.endpointId,
        model: override?.model,
        attachment_ids: attachmentIds,
        // Only meaningful when this turn creates the conversation; the backend
        // ignores it when continuing one.
        ephemeral: wasNew && options.ephemeral ? true : undefined,
        // Likewise: a thread's mode and project are set once, at creation. The
        // backend re-reads them off the conversation for every later turn, so
        // sending them again would be a second source for one fact.
        mode: wasNew ? options.mode?.() : undefined,
        project_id: wasNew ? options.projectId?.() : undefined,
        // The level, on the other hand, is sent every time: it is the one binding
        // fact that moves, and the composer's control moves it by being read here on
        // the next send rather than by a write of its own.
        permission_level: options.permission?.(),
        continues_message_id: continuesMessageId,
      });
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        // A run is already active on this conversation — drop the optimistic
        // turn we just queued (it was never accepted) and surface the one
        // that's actually in flight instead of silently discarding this send.
        setMessages(
          reconcile(
            messages.filter((m) => m.id !== userMsg.id && m.id !== assistantId),
          ),
        );
        toast.error("A response is still in progress in this conversation.");
        setSending(false);
        setTitlePending(false);
        if (activeConversationId) void reattachToLiveRun(activeConversationId);
        return;
      }
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to reach the assistant.",
      );
      patchById(assistantId, (m) => (m.streaming = false));
      setSending(false);
      setTitlePending(false);
      return;
    }
    activeConversationId = created.conversation_id;
    // Accepted — so the backend has retired the stop marker this turn resumes.
    // Echo that now rather than waiting for the run to finish: the warning is about
    // a turn the operator has visibly just resumed, and leaving it up for the length
    // of the new run reads as the Continue press having done nothing.
    if (continuesMessageId !== undefined)
      patchById(continuesMessageId, (m) => {
        m.blocked = false;
        m.blockedDetail = undefined;
      });
    await driveRun(created.run_id, assistantId, wasNew);
  }

  /** Resume a turn a bound stopped (inactivity/wall-clock timeout or cancel) by
   *  sending a fresh "Continue." turn on the same conversation. Reuses the ordinary
   *  send path, so a small "Continue." bubble appears in the transcript and the
   *  model picks up where the prior turn left off.
   *
   *  ``messageId`` is the stopped turn's branch node id — the backend retires that
   *  turn's stop marker when it accepts the turn, so the warning doesn't linger
   *  under a turn the operator already resumed, and a reload reads the retirement
   *  back from the store rather than resurrecting it. */
  async function continueTurn(messageId?: string): Promise<void> {
    // A blocked turn is settled, so this is a fresh turn — but if a run is already
    // in flight (the operator started a new one), don't inject "Continue." as a
    // steering message; just no-op.
    if (activeConversationId === null || sending()) return;
    await send(CONTINUE_PROMPT, [], messageId);
  }

  /** Cancel the in-flight run for real: tell the backend to stop it (it keeps
   *  running even when the SSE is dropped), then abort the local stream and clear
   *  the streaming state. Safe to call with no active run. */
  async function cancel(): Promise<void> {
    const runId = activeRunId;
    // Mark the cancel before the abort unwinds the drive, so its `adoptServerMeta`
    // in `finally` keeps the in-flight turn instead of reseating it away.
    cancelled = true;
    if (runId) {
      try {
        await api.post(`/runs/${runId}/cancel`, {});
      } catch (err) {
        // The local abort below still stops the UI; surface but don't block.
        toast.error(
          (err as { detail?: string })?.detail ?? "Unable to cancel the run.",
        );
      }
    }
    activeRunId = null;
    controller?.abort();
    controller = null;
    setMessages(
      produce((m) => {
        // A cancelled turn may currently be `streaming` (normal in-flight) or
        // `detached` (transport gave up, but we still guarded it as in-flight)
        // — either is the one this cancel is aimed at.
        const target = m.find((x) => x.streaming || x.detached);
        if (target) {
          target.streaming = false;
          target.queued = false;
          target.detached = false;
        }
      }),
    );
    setSending(false);
    setDetached(false);
    // A cancel with steering messages still queued: they'll never be injected
    // now, so restore them to the composer. (The drive's own teardown also calls
    // this; it's idempotent, and this covers the detached case it skips.)
    restoreUndelivered();
  }

  /** Withdraw a steering message that's still queued on the live run. No
   *  optimistic removal: a 404 means the run consumed it in the meantime — the
   *  message is part of the turn and its bubble must stay. On success the
   *  bubble drops here and the `message.withdrawn` fold is a no-op. */
  async function withdrawQueued(queuedMessageId: string): Promise<void> {
    const runId = activeRunId;
    if (!runId) return;
    try {
      await api.del(`/runs/${runId}/messages/${queuedMessageId}`);
      setMessages(
        reconcile(
          messages.filter(
            (m) => !(m.queuedMessageId === queuedMessageId && m.queuedPending),
          ),
        ),
      );
    } catch (err) {
      if (isApiError(err) && err.status === 404) {
        toast.warn(
          "Too late to withdraw — the message already reached the model.",
        );
      } else {
        toast.error(
          (err as { detail?: string })?.detail ??
            "Unable to withdraw the message.",
        );
      }
    }
  }

  /** Rewrite a steering message that's still queued on the live run (it keeps
   *  its id and place in the queue). No optimistic update: the bubble changes
   *  only once the backend accepts, and a 404 means the run consumed the
   *  message in the meantime — the original text is what the model saw, so the
   *  bubble must keep it. */
  async function editQueued(
    queuedMessageId: string,
    text: string,
  ): Promise<void> {
    const runId = activeRunId;
    if (!runId) return;
    try {
      await api.patch(`/runs/${runId}/messages/${queuedMessageId}`, { text });
      setMessages(
        produce((list) => {
          const bubble = list.find(
            (m) => m.queuedMessageId === queuedMessageId && m.queuedPending,
          );
          if (bubble) bubble.content = text;
        }),
      );
    } catch (err) {
      if (isApiError(err) && err.status === 404) {
        toast.warn("Too late to edit — the message already reached the model.");
      } else {
        toast.error(
          (err as { detail?: string })?.detail ?? "Unable to edit the message.",
        );
      }
    }
  }

  /** POST a batch of approval decisions for a message's run, then apply an
   *  optimistic patch. The open run stream resumes with the results — the parked
   *  run requires a decision covering *every* pending call, which is why each
   *  surface batches its decisions into one POST. */
  async function submitDecisions(
    messageId: string,
    decisions: ApprovalDecision[],
    optimistic: (m: ChatMessage) => void,
  ): Promise<void> {
    const msg = messages.find((m) => m.id === messageId);
    if (!msg?.runId) return;
    try {
      await api.post(`/runs/${msg.runId}/approve`, { decisions });
      patchById(messageId, optimistic);
      // A recorded conversation grant must show on the strip now, not on the next
      // stream toggle — nudge the grants resource to refetch.
      if (decisions.some((d) => d.scope === "conversation")) {
        setGrantsRevision((n) => n + 1);
      }
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        // The decision was already made elsewhere (a second tab, a retried
        // request that landed after the run resumed) — resubmitting would just
        // 409 forever. Mark the pending cards stale (non-interactive, with a
        // note) instead of leaving them re-clickable, then refetch so the
        // transcript catches up to whatever actually happened.
        patchById(messageId, (m) => {
          for (const b of m.blocks ?? []) {
            if (b.kind === "approval") b.approval.stale = true;
            else if (b.kind === "host_command" && b.command.phase === "pending")
              b.command.phase = "stale";
          }
        });
        toast.error("This decision was already made elsewhere.");
        void reconcileStaleDecision();
        return;
      }
      // A transient failure (network blip, 5xx): the decision may not have
      // landed at all, so keep the card interactive and let the operator retry.
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to submit the decision.",
      );
    }
  }

  /** Decide a message's pending approvals; the cards clear once submitted. */
  const resolveApproval = (messageId: string, decisions: ApprovalDecision[]) =>
    submitDecisions(messageId, decisions, (m) => {
      if (m.blocks) m.blocks = m.blocks.filter((b) => b.kind !== "approval");
    });

  /** Decide a message's host-command approvals. Approved commands begin running
   *  and denied ones close out optimistically; the stream confirms the outcome. */
  const resolveHostCommands = (
    messageId: string,
    decisions: ApprovalDecision[],
  ) =>
    submitDecisions(messageId, decisions, (m) => {
      for (const d of decisions) {
        const b = m.blocks?.find(
          (x): x is HostCommandBlock =>
            x.kind === "host_command" &&
            x.command.toolCallId === d.tool_call_id,
        );
        if (b) b.command.phase = d.approved ? "running" : "denied";
      }
    });

  /* ── Branching: regenerate / edit / version-cycle / rewind / delete ─────────
     Each is a thin relay to a live backend endpoint. The regenerate/edit ops
     re-drive a run (optimistically resetting the path, then streaming the new
     answer in); the rest reseat the store from a returned conversation detail.
     All guard on a persisted conversation and surface failures via toast. */

  function reseatFromDetail(detail: ConversationDetailDTO): void {
    setMessages(reconcile(detail.messages.map(toMessage)));
    // The active path moved (version switch / rewind / delete), so the window
    // state moves with it.
    setUsage(detail.context);
    // Re-seed the conversation-level snapshot history from the same detail.
    setSnapshots((detail.snapshots ?? []).map(toViewSnapshotRef));
  }

  function toastError(err: unknown, fallback: string): void {
    toast.error((err as { detail?: string })?.detail ?? fallback);
  }

  /** Re-answer an assistant turn from the preceding request, using the current
   *  model selection; the new answer becomes a sibling version. `messageId` is
   *  the assistant message's id. */
  async function regenerate(messageId: string): Promise<void> {
    if (activeConversationId === null || sending()) return;
    const i = messages.findIndex(
      (m) => m.id === messageId && m.role === "assistant",
    );
    if (i < 0) return;
    setSending(true);
    const override = options.selection?.();
    const sel = override ?? effectiveSelection();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/regenerate", {
        conversation_id: activeConversationId,
        message_id: messageId,
        endpoint_id: override?.endpointId,
        model: override?.model,
      });
      const reset: ChatMessage = {
        id: messageId,
        role: "assistant",
        model: sel?.model,
        content: "",
        blocks: [],
        streaming: true,
        queued: true,
        createdAt: new Date().toISOString(),
      };
      setMessages(reconcile([...messages.slice(0, i), reset]));
      await driveRun(created.run_id, messageId);
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        toast.error("A response is still in progress in this conversation.");
        setSending(false);
        if (activeConversationId) void reattachToLiveRun(activeConversationId);
        return;
      }
      toastError(err, "Unable to regenerate the answer.");
      setSending(false);
    }
  }

  /** Re-ask an edited user turn as a new version; a fresh answer streams in.
   *  `messageId` is the user message's id. */
  async function edit(
    messageId: string,
    newText: string,
    selection?: ModelSelection | null,
    attachmentIds?: string[],
  ): Promise<void> {
    const j = messages.findIndex(
      (m) => m.id === messageId && m.role === "user",
    );
    if (j < 0 || activeConversationId === null || sending()) return;
    // Reuse the turn's existing attachments unless the caller supplies a new set.
    const ids = attachmentIds ?? messages[j].attachmentIds ?? [];
    if (!newText.trim() && ids.length === 0) return;
    setSending(true);
    const override = selection ?? options.selection?.();
    const sel = override ?? effectiveSelection();
    const prompt = newText.trim();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/edit", {
        conversation_id: activeConversationId,
        message_id: messageId,
        prompt,
        endpoint_id: override?.endpointId,
        model: override?.model,
        attachment_ids: ids,
      });
      const editedUser: ChatMessage = {
        ...messages[j],
        content: prompt,
        attachmentIds: ids.length ? ids : undefined,
      };
      const assistantId = nextId("a");
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        model: sel?.model,
        content: "",
        blocks: [],
        streaming: true,
        queued: true,
        createdAt: new Date().toISOString(),
      };
      setMessages(
        reconcile([...messages.slice(0, j), editedUser, assistantMsg]),
      );
      await driveRun(created.run_id, assistantId);
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        toast.error("A response is still in progress in this conversation.");
        setSending(false);
        if (activeConversationId) void reattachToLiveRun(activeConversationId);
        return;
      }
      toastError(err, "Unable to submit the edit.");
      setSending(false);
    }
  }

  /** Switch a turn to a sibling version; reseat the store from the returned
   *  active path and refresh the sidebar. */
  async function switchVersion(
    messageId: string,
    index: number,
  ): Promise<void> {
    if (activeConversationId === null) return;
    // Stop any live run first: the reseat below replaces the store, and a still-
    // streaming foldEvent would keep patching a message the reseat removed.
    if (sending()) await cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${activeConversationId}/messages/${messageId}/version`,
        { index },
      );
      reseatFromDetail(detail);
      options.onTurnComplete?.();
    } catch (err) {
      toastError(err, "Unable to switch versions.");
    }
  }

  /** Rewind the thread to end at a turn; the operator's next send branches. */
  async function rewind(messageId: string): Promise<void> {
    if (activeConversationId === null) return;
    if (sending()) await cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${activeConversationId}/messages/${messageId}/rewind`,
        {},
      );
      reseatFromDetail(detail);
      options.onTurnComplete?.();
      toast.success("Rewound — your next message starts a new branch");
    } catch (err) {
      toastError(err, "Unable to rewind the conversation.");
    }
  }

  /** Fold this thread's older turns into a summary now, rather than waiting for it to
   *  reach the automatic threshold — for a thread the operator knows is about to need the
   *  room. Reseats from the returned active path like the other transcript-mutating
   *  actions, so the new divider renders from exactly the shape a cold read gives. */
  async function compactNow(): Promise<void> {
    if (activeConversationId === null) return;
    if (sending()) await cancel();
    try {
      const detail = await api.post<ConversationDetailDTO>(
        `/conversations/${activeConversationId}/compact`,
        {},
      );
      reseatFromDetail(detail);
      toast.success("Earlier turns folded into a summary");
    } catch (err) {
      toastError(err, "Unable to compact this conversation.");
    }
  }

  /** Delete a turn and everything after it; reseat from the returned active path
   *  (the DELETE returns the post-delete detail, like version-switch/rewind). */
  async function removeMessage(
    messageId: string,
    purgeImages = false,
  ): Promise<void> {
    if (activeConversationId === null) return;
    if (sending()) await cancel();
    try {
      const q = purgeImages ? "?purgeImages=true" : "";
      const detail = await api.del<ConversationDetailDTO>(
        `/conversations/${activeConversationId}/messages/${messageId}${q}`,
      );
      reseatFromDetail(detail);
      options.onTurnComplete?.();
    } catch (err) {
      toastError(err, "Unable to delete the message.");
    }
  }

  /** Pin/unpin a turn. The backend owns the flag; this optimistically echoes the
   *  toggle and reverts if the POST fails. */
  async function toggleMessagePin(messageId: string): Promise<void> {
    if (activeConversationId === null) return;
    const msg = messages.find((m) => m.id === messageId);
    if (!msg) return;
    const next = !msg.pinned;
    patchById(messageId, (m) => {
      m.pinned = next;
    });
    try {
      await api.post(
        `/conversations/${activeConversationId}/messages/${messageId}/pin`,
        { pinned: next },
      );
    } catch (err) {
      patchById(messageId, (m) => {
        m.pinned = !next;
      });
      toastError(err, "Unable to update the pin.");
    }
  }

  // Cold-read reattach: a thread loaded mid-stream carries its in-flight run
  // (`options.activeRun`), so resume it — fold the full replay onto a freshly
  // seeded assistant turn and continue live — instead of rendering the thread
  // reply-less. The source is withheld (→ undefined) while history loads, so this
  // never fires on an empty seed; it runs once per run (`reattachedRunId`) and not
  // for a run we're already driving.
  createEffect(() => {
    const ar = options.activeRun?.();
    if (!ar || ar.id === reattachedRunId || ar.id === activeRunId) return;
    reattachedRunId = ar.id;
    void reattachRun(ar.id, { fromSeq: 0 });
  });

  /** Flip a snapshot's keeper bookmark: optimistically replace the array element
   *  (a spread copy — never mutate the stored ref in place), then confirm against
   *  the backend, reverting the same way on failure. */
  async function toggleSnapshotKeeper(
    snapshotId: string,
    keeper: boolean,
  ): Promise<void> {
    setSnapshots((prev) =>
      prev.map((s) => (s.snapshotId === snapshotId ? { ...s, keeper } : s)),
    );
    try {
      await api.post(`/views/snapshots/${snapshotId}/keeper`, { keeper });
    } catch (err) {
      setSnapshots((prev) =>
        prev.map((s) =>
          s.snapshotId === snapshotId ? { ...s, keeper: !keeper } : s,
        ),
      );
      toastError(err, "Unable to update the keeper flag.");
    }
  }

  onCleanup(() => controller?.abort());

  return {
    messages,
    /** The conversation's workspace snapshots (git-style history), newest last. */
    snapshots,
    /** The stream path of this thread's live agent browser, or null when it has none. */
    browserStream,
    /** Drop the live browser — the panel calls this when its socket reports the session
     *  is gone, which is the only signal a reap between turns can produce. */
    clearBrowserStream: () => setBrowserStream(null),
    toggleSnapshotKeeper,
    sending,
    errored,
    /** True while the live run's transport is detached (reconnect budget
     *  exhausted) — the run may still be alive server-side, awaiting a
     *  manual/automatic re-attach rather than being over. */
    detached,
    /** True while a sensitive tool call has parked this run awaiting the
     *  operator's decision — the main room mirrors it to the global
     *  `awaitingApproval` echo (nav rail warn tone, favicon attention tint). */
    awaitingApproval,
    titlePending,
    reattaching,
    usage,
    stats,
    plan,
    /** The run currently streaming into this store, or null. */
    activeRunId: () => activeRunId,
    /** Highest event seq folded so far — the resume point for a reattach. */
    lastSeq: () => maxFoldedSeq,
    send,
    /** Resume a turn a bound stopped by sending a fresh "Continue." turn. */
    continueTurn,
    cancel,
    /** Withdraw a queued (not-yet-injected) steering message from the live run. */
    withdrawQueued,
    /** Rewrite a queued (not-yet-injected) steering message in place. */
    editQueued,
    /** Text of queued messages the run never consumed (restored on terminal) —
     *  the screen prefills the composer with it, then clears it. */
    undeliveredDraft,
    clearUndeliveredDraft: () => setUndeliveredDraft(null),
    reattachRun,
    resolveApproval,
    resolveHostCommands,
    regenerate,
    edit,
    switchVersion,
    rewind,
    compactNow,
    removeMessage,
    toggleMessagePin,
  };
}

/* ── The persistent main-chat controller ──────────────────────────────────────
   The chat room's stream, its selected conversation, and its loaded history live
   here — under a never-disposed root — rather than inside the screen component.
   Navigating away and back therefore no longer tears down an in-flight turn: a
   run started on one visit keeps streaming into this store, and re-entering the
   room re-binds to it instead of fetching an as-yet-unpersisted (empty) thread.
   (A turn's messages are only persisted when it finishes, so a mid-stream refetch
   would otherwise read an empty conversation and the room would render blank.)

   The compare panes still spin up their own throwaway `createChatStream`s — only
   the single main room is this long-lived singleton. */
export interface MainChat {
  currentId: Accessor<string | null>;
  setCurrentId: (id: string | null) => void;
  stream: ReturnType<typeof createChatStream>;
  /** Whether the one-time warm-resume entry intent has run this app session. The
   *  flag is part of the singleton so it survives navigation — see the screen. */
  warmResolved: Accessor<boolean>;
  markWarmResolved: () => void;
  /** **The mode context** — which kind of work the operator is looking at.
   *
   *  One signal doing three jobs, because they are one fact: it decides what the
   *  *next new* conversation will be, which threads the rail lists, and which
   *  signature accent the whole window paints. Opening an existing thread sets it
   *  from that thread, so the three never disagree with what is on screen.
   *
   *  Lives on the singleton rather than the screen because the send path reads it,
   *  the rail reads it, and a composer draft that survives navigation should keep
   *  the mode it was written for. A saved thread's *stored* binding stays the
   *  backend's — this is only what the client is currently pointed at. */
  mode: Accessor<SessionMode>;
  setMode: (mode: SessionMode) => void;
  codeProjectId: Accessor<string | undefined>;
  setCodeProjectId: (id: string | undefined) => void;
  /** How far the model may go in the open thread. Unlike the mode this is sent on
   *  every turn and persisted per conversation, so the composer's control moves it
   *  mid-thread; seeded from the loaded thread so a reload comes back where the
   *  operator left it, and reset to the mode's default when a new thread is
   *  staged. */
  permission: Accessor<PermissionLevel>;
  setPermission: (level: PermissionLevel) => void;
}

let _mainChat: MainChat | undefined;

/** The app-wide chat room controller — created once, then reused across mounts. */
export function mainChat(): MainChat {
  if (_mainChat) return _mainChat;
  return (_mainChat = createRoot(() => {
    const [currentId, setCurrentId] = createSignal<string | null>(null);
    const [mode, setMode] = createSignal<SessionMode>(DEFAULT_SESSION_MODE);
    const [codeProjectId, setCodeProjectId] = createSignal<string | undefined>(
      undefined,
    );
    const [permission, setPermission] = createSignal<PermissionLevel>(
      DEFAULT_PERMISSION_LEVEL,
    );
    const session = useChatSession(currentId);
    const stream = createChatStream(
      // Withhold the source while history loads — the resource still reports the
      // previous thread's value across a source change (Solid retains it), and
      // feeding that to the stream would seed the wrong thread.
      () => (session.loading ? undefined : session()?.messages),
      currentId,
      {
        onConversationStarted: (id) => setCurrentId(id),
        onTurnComplete: () => refreshSessions(),
        // Withheld in lockstep with the history above, so the meter seeds from the
        // loaded thread rather than the retained value of the one just left.
        initialContext: () =>
          session.loading ? undefined : session()?.context,
        // Same lockstep: the loaded thread's cumulative readout.
        initialStats: () => (session.loading ? undefined : session()?.stats),
        // Same lockstep: the in-flight run of the loaded thread, for a cold-read
        // reattach (a page reload mid-stream).
        activeRun: () => (session.loading ? undefined : session()?.activeRun),
        // Same lockstep: the loaded thread's git-style snapshot history.
        initialSnapshots: () =>
          session.loading ? undefined : session()?.snapshots,
        // Read only when a send creates the conversation.
        mode,
        projectId: codeProjectId,
        // Read on every send — the level is the one binding fact that moves.
        permission,
      },
    );
    // Opening a thread points the client at what that thread *is*: its mode moves the
    // rail and the signature accent, its level seats the composer's control. Both are
    // seeded from the load rather than left on the previous thread's values, which is
    // what stops the window from claiming to be in a code session while a normal one
    // is on screen. Staging a new thread (`currentId === null`) leaves the mode where
    // the operator put it — that choice is the whole point of the switch — and returns
    // the level to the default, since there is no thread yet to have a level.
    createEffect(() => {
      if (currentId() === null) {
        setPermission(DEFAULT_PERMISSION_LEVEL);
        return;
      }
      if (session.loading) return;
      const loaded = session();
      if (!loaded) return;
      setMode(loaded.mode);
      setPermission(loaded.permission);
    });
    // The mode context, stamped on the document root so the cascade paints the
    // signature accent for it. A DOM write rather than a rendered attribute because
    // the target is `<html>`, which no component owns — the same shape `applyTheme`
    // has for the other axis.
    createEffect(() => applySessionMode(mode()));
    // Reattach when the tab returns to the foreground or the network comes back.
    // A backgrounded tab throttles the SSE reader until it stalls; on return we
    // replay from the last folded seq — resuming a still-live run or folding the
    // tail of one that finished while we were away (which clears the frozen
    // streaming state via the drive's finally). No-op when nothing is in flight.
    const resume = () => {
      const runId = stream.activeRunId();
      const inFlight =
        stream.sending() || stream.messages.some((m) => m.streaming);
      if (runId && inFlight) {
        void stream.reattachRun(runId, { fromSeq: stream.lastSeq() });
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") resume();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", resume);
    onCleanup(() => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", resume);
    });
    // Mirror the main room's streaming state to the global flag the nav rail reads,
    // so the Chat item shows a live indicator while a turn runs — even from another
    // section. Only the main room drives it (compare panes are ephemeral).
    createEffect(() => setChatBusy(stream.sending()));
    // A turn *starting* changes the list as much as one finishing: each row's
    // activity edge is server-derived, so the list has to be re-read for the
    // running thread to light up. `onTurnComplete` above covers the other edge.
    createEffect(
      on(
        () => stream.sending(),
        (sending) => {
          if (sending) refreshSessions();
        },
        { defer: true },
      ),
    );
    // Same main-room-only mirror for the last-run-error echo, so the favicon can flag a
    // failed run from any screen.
    createEffect(() => setRunErrored(stream.errored()));
    // Same mirror for the awaiting-approval echo, so the nav rail and favicon can flag
    // a parked run needing a decision from any screen, not just while on /chat.
    createEffect(() => setAwaitingApproval(stream.awaitingApproval()));
    // Read-on-view: the one place a thread selection lands, regardless of whether it
    // came from the RECENTS rail, the chat screen's warm-resume, or a notification's
    // deep-link — so opening a conversation always clears its unread notifications
    // without every caller having to remember to do it.
    createEffect(() => {
      const id = currentId();
      if (id) markConversationRead(id);
    });
    const [warmResolved, setWarmResolved] = createSignal(false);
    return {
      currentId,
      setCurrentId,
      stream,
      warmResolved,
      markWarmResolved: () => setWarmResolved(true),
      mode,
      setMode,
      codeProjectId,
      setCodeProjectId,
      permission,
      setPermission,
    } satisfies MainChat;
  }));
}
