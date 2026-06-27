import {
  createEffect,
  createResource,
  createRoot,
  createSignal,
  onCleanup,
  type Accessor,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api } from "~/lib/api";
import { readLS, writeLS } from "~/lib/storage";
import { setChatBusy, setRunErrored } from "~/lib/stores/chatActivity";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import { streamRun, type ContextWindow, type RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import type {
  ActiveRun,
  ApprovalDecision,
  ApprovalGrant,
  AssistantBlock,
  ChatMessage,
  ChatSession,
  ChatSummary,
  ContextUsage,
  HostCommand,
  HostCommandBlock,
  HostCommandPhase,
  SnapshotDiff,
  SnapshotFile,
  ToolBlock,
  ToolInvocation,
  ViewSnapshotRef,
  ViewVersionRef,
} from "./model";

/** The one approval-gated tool that runs on the real host (vs. the sandbox). Its
 *  approval + execution render as a single persistent terminal, never a generic
 *  approval card or tool card. */
export const HOST_COMMAND_TOOL = "code_run_host_command";

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
}

interface ToolCallDTO {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: ToolInvocation["status"];
  result?: unknown;
  error?: string | null;
}

interface ViewVersionDTO {
  version_id: string;
  title: string;
  filename: string;
  content_type: string;
  kind: ViewVersionRef["kind"];
}

interface ViewSnapshotDTO {
  snapshot_id: string;
  title: string | null;
  created_at: string;
  files_changed: number;
  summary: string;
}

interface MessageDTO {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string | null;
  tools: ToolCallDTO[];
  versions?: ViewVersionDTO[];
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
}

interface ActiveRunDTO {
  id: string;
  status: string;
  last_seq: number;
}

interface ConversationDetailDTO extends ConversationSummaryDTO {
  messages: MessageDTO[];
  /** Context-window state reconstructed from the last turn's usage; null when
   *  unavailable. Seeds the meter so an existing thread shows fullness on load. */
  context: ContextWindow | null;
  /** The in-flight run driving this thread, if a turn is still streaming
   *  server-side; absent/null otherwise. Lets a cold read reattach to it. */
  active_run?: ActiveRunDTO | null;
  /** Workspace snapshots captured across the thread (newest last). Conversation-
   *  scoped — not folded onto a message — so the viewport seeds them separately. */
  snapshots?: ViewSnapshotDTO[];
}

function toActiveRun(dto: ActiveRunDTO | null | undefined): ActiveRun | null {
  return dto ? { id: dto.id, status: dto.status, lastSeq: dto.last_seq } : null;
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

/** Map a View-version DTO/event to the seam type. Shared by the cold read (history
 *  detail) and the warm stream (`view.version`) so both render identically. */
function toViewVersionRef(dto: ViewVersionDTO): ViewVersionRef {
  return {
    versionId: dto.version_id,
    title: dto.title,
    filename: dto.filename,
    contentType: dto.content_type,
    kind: dto.kind,
  };
}

/** Map a workspace-snapshot DTO/event to the seam type. Shared by the cold read
 *  (conversation detail) and the warm stream (`view.snapshot`). */
function toViewSnapshotRef(dto: ViewSnapshotDTO): ViewSnapshotRef {
  return {
    snapshotId: dto.snapshot_id,
    title: dto.title ?? undefined,
    createdAt: dto.created_at,
    filesChanged: dto.files_changed,
    summary: dto.summary,
  };
}

function toTool(dto: ToolCallDTO): ToolInvocation {
  return {
    id: dto.id,
    name: dto.name,
    args: formatArgs(dto.args),
    status: dto.status,
    result: stringifyResult(dto.result),
    error: dto.error ?? undefined,
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
  };
  if (dto.role !== "assistant") return base;
  // Cold history is still flat (no recorded emission order), so reconstruct the
  // turn's blocks in the legacy lane order — reasoning, the tool/host calls,
  // artifacts, then the answer. (Once the backend persists ordered blocks, map
  // them straight through here; the live stream already carries true order.)
  const blocks: AssistantBlock[] = [];
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
  }
  for (const v of dto.versions ?? [])
    blocks.push({
      kind: "view_version",
      id: `${dto.id}-${v.version_id}`,
      version: toViewVersionRef(v),
    });
  if (dto.content)
    blocks.push({ kind: "text", id: `${dto.id}-text`, text: dto.content });
  // The answer lives in the text block(s); keep `content` empty for assistant
  // turns so it isn't a second, divergent copy of the same text.
  return { ...base, content: "", blocks, model: dto.model ?? undefined };
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
    model: "",
    messages: dto.messages.map(toMessage),
    context: dto.context,
    activeRun: toActiveRun(dto.active_run),
    snapshots: (dto.snapshots ?? []).map(toViewSnapshotRef),
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

/** The per-file unified diffs for a snapshot (empty `diff` for binary files). */
export async function fetchSnapshotDiffs(
  snapshotId: string,
): Promise<SnapshotDiff[]> {
  const rows = await api.get<SnapshotDiffDTO[]>(
    `/views/snapshots/${snapshotId}/diff`,
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
  // The conversation doesn't persist its endpoint, so name it with the operator's
  // current pick — the same selection a chat turn sends — rather than a default role
  // the backend may not have bound.
  const selection = effectiveSelection();
  const summary = await api.post<ConversationSummaryDTO>(
    `/conversations/${id}/retitle`,
    { endpoint_id: selection?.endpointId, model: selection?.model },
  );
  if (summary.title) revealTitle(id, summary.title);
  refreshSessions();
}

export async function deleteConversation(
  id: string,
  purgeImages = false,
): Promise<void> {
  const q = purgeImages ? "?purgeImages=true" : "";
  await api.del(`/conversations/${id}${q}`);
  refreshSessions();
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

/** Revoke a conversation auto-approval — the next call to that tool asks again. */
export async function revokeGrant(
  conversationId: string,
  toolName: string,
): Promise<void> {
  await api.del(
    `/conversations/${conversationId}/grants/${encodeURIComponent(toolName)}`,
  );
}

/* ── Streaming controller ─────────────────────────────────────────────────────
   Drives the live message list off a run's SSE stream. The public shape
   (messages, sending, send, resolveApproval) is the seam the screen renders. */

interface ChatCreatedDTO {
  run_id: string;
  conversation_id: string;
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
  /** The loaded conversation's context-window state, seeded alongside its history
   *  so an existing thread shows window fullness before its next turn runs. */
  initialContext?: () => ContextUsage | null | undefined;
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
  const [sending, setSending] = createSignal(false);
  // True when this room's last run ended in `run.error`; cleared when the next run
  // starts (in `driveRun`). The main room mirrors it to the global `runErrored` echo
  // so the favicon can flag a failed run — compare panes keep it local.
  const [errored, setErrored] = createSignal(false);
  // A brand-new thread is auto-named during its first turn; this drives a "working"
  // throbber on the title from that turn's start until the name lands
  // (`conversation.titled`, which the reveal then animates) or the turn ends without
  // one. Backend-owned outcome — the frontend only reflects the in-flight window.
  const [titlePending, setTitlePending] = createSignal(false);
  // The latest run's context-window state, as derived by the backend. Null until
  // a run reports it against a known window (loaded history carries none), which
  // is when the context meter first appears.
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  // True while a reattach (replay from a known run) is folding in — drives the
  // "RESYNCING…" affordance, distinct from a fresh turn's `sending`.
  const [reattaching, setReattaching] = createSignal(false);
  let controller: AbortController | null = null;
  // The run currently streaming, if any — needed to cancel it on the backend
  // (aborting the SSE alone leaves the run executing server-side).
  let activeRunId: string | null = null;
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
    // A new thread starts a fresh event sequence; drop the prior run's fold/resume
    // bookkeeping so its seqs don't suppress the next run's events.
    maxFoldedSeq = 0;
    activeRunId = null;
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
    // Seed the git-style snapshot history from the loaded thread (empty for a new
    // conversation); the live `view.snapshot` event appends to it from here.
    setSnapshots(k === null ? [] : (options.initialSnapshots?.() ?? []));
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

  function foldEvent(assistantId: string, ev: RunEvent): void {
    // Idempotency: `seq` is monotonic per run, so an event at or below the high-
    // water mark was already folded (a reattach replay overlapping a still-live
    // reader). Skipping it stops a re-applied `answer.delta` from doubling text.
    if (ev.seq <= maxFoldedSeq) return;
    maxFoldedSeq = ev.seq;
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
            b.tool.progress = undefined; // the run is over — drop the spin-up note
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
      case "approval.required":
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, {
              command:
                typeof ev.args.command === "string" ? ev.args.command : "",
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
              args: ev.args,
              summary: ev.summary,
              explanation: ev.explanation ?? undefined,
            },
          });
        });
        break;
      case "view.version":
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "view_version",
            id: `view-version-${ev.version_id}`,
            version: toViewVersionRef(ev),
          });
        });
        break;
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
      case "view.snapshot": {
        // Conversation-scoped, not a message block: append to the snapshot history
        // (dedup by id, since a reattach replay can re-deliver it).
        const ref = toViewSnapshotRef(ev);
        setSnapshots((prev) =>
          prev.some((s) => s.snapshotId === ref.snapshotId)
            ? prev
            : [...prev, ref],
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
        break;
      // run.started / run.ended / step.* / limit.notice: no store change
    }
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
    activeRunId = runId;
    setErrored(false); // a fresh run supersedes any prior failure
    // Re-anchor the fold high-water mark to this run's sequence. Each run owns a
    // fresh event stream whose seq restarts at 1, so a new turn (fromSeq omitted →
    // 0) must drop the *previous* run's mark — otherwise its early events (seq ≤
    // that stale mark) are suppressed in `foldEvent` and the answer streams in
    // blank until the counter catches up (or never, if this turn is shorter). A
    // reattach passes `fromSeq` = the last seq it folded, replaying only the gap.
    maxFoldedSeq = fromSeq ?? 0;
    patchById(assistantId, (m) => (m.runId = runId));
    let connected = false;
    try {
      controller = new AbortController();
      await streamRun(runId, {
        signal: controller.signal,
        fromSeq,
        onEvent: (ev) => {
          // First event = the transport is live again; let a reattach drop its
          // "RESYNCING…" badge here, so it shows only across the reconnect latency.
          if (!connected) {
            connected = true;
            onConnected?.();
          }
          foldEvent(assistantId, ev);
        },
      });
    } catch (err) {
      if (myGen === driveGen)
        toast.error(
          (err as { detail?: string })?.detail ??
            "Unable to reach the assistant.",
        );
    } finally {
      // Skip teardown when superseded by a reattach/thread-switch — that drive
      // owns the state now, and clearing it here would race it.
      if (myGen === driveGen) {
        activeRunId = null;
        patchById(assistantId, (m) => (m.streaming = false));
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
    let assistantId = messages.find(
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
      patchById(assistantId, (m) => (m.streaming = true));
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
    // answer still shows rather than a blank assistant turn.
    if (
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
      reseatFromDetail(detail);
      return;
    }
    setMessages(
      produce((list) => {
        for (let i = 0; i < list.length; i++) {
          list[i].id = server[i].id;
          list[i].versionIndex = server[i].version_index;
          list[i].versionCount = server[i].version_count;
          list[i].pinned = server[i].pinned;
        }
      }),
    );
  }

  async function send(
    text: string,
    attachmentIds: string[] = [],
  ): Promise<void> {
    // A turn needs either prompt text or at least one attachment to send.
    if ((!text.trim() && attachmentIds.length === 0) || sending()) return;
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
    const selection = options.selection?.() ?? effectiveSelection();
    const assistantId = nextId("a");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      model: selection?.model,
      content: "",
      blocks: [],
      streaming: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(produce((m) => m.push(userMsg, assistantMsg)));

    let created: ChatCreatedDTO;
    try {
      created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId ?? undefined,
        endpoint_id: selection?.endpointId,
        model: selection?.model,
        attachment_ids: attachmentIds,
        // Only meaningful when this turn creates the conversation; the backend
        // ignores it when continuing one.
        ephemeral: wasNew && options.ephemeral ? true : undefined,
      });
    } catch (err) {
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
    await driveRun(created.run_id, assistantId, wasNew);
  }

  /** Cancel the in-flight run for real: tell the backend to stop it (it keeps
   *  running even when the SSE is dropped), then abort the local stream and clear
   *  the streaming state. Safe to call with no active run. */
  async function cancel(): Promise<void> {
    const runId = activeRunId;
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
        const streaming = m.find((x) => x.streaming);
        if (streaming) streaming.streaming = false;
      }),
    );
    setSending(false);
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
    const sel = options.selection?.() ?? effectiveSelection();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/regenerate", {
        conversation_id: activeConversationId,
        message_id: messageId,
        endpoint_id: sel?.endpointId,
        model: sel?.model,
      });
      const reset: ChatMessage = {
        id: messageId,
        role: "assistant",
        model: sel?.model,
        content: "",
        blocks: [],
        streaming: true,
        createdAt: new Date().toISOString(),
      };
      setMessages(reconcile([...messages.slice(0, i), reset]));
      await driveRun(created.run_id, messageId);
    } catch (err) {
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
    const sel = selection ?? options.selection?.() ?? effectiveSelection();
    const prompt = newText.trim();
    try {
      const created = await api.post<ChatCreatedDTO>("/chat/edit", {
        conversation_id: activeConversationId,
        message_id: messageId,
        prompt,
        endpoint_id: sel?.endpointId,
        model: sel?.model,
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
        createdAt: new Date().toISOString(),
      };
      setMessages(
        reconcile([...messages.slice(0, j), editedUser, assistantMsg]),
      );
      await driveRun(created.run_id, assistantId);
    } catch (err) {
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

  onCleanup(() => controller?.abort());

  return {
    messages,
    /** The conversation's workspace snapshots (git-style history), newest last. */
    snapshots,
    sending,
    errored,
    titlePending,
    reattaching,
    usage,
    /** The run currently streaming into this store, or null. */
    activeRunId: () => activeRunId,
    /** Highest event seq folded so far — the resume point for a reattach. */
    lastSeq: () => maxFoldedSeq,
    send,
    cancel,
    reattachRun,
    resolveApproval,
    resolveHostCommands,
    regenerate,
    edit,
    switchVersion,
    rewind,
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
}

let _mainChat: MainChat | undefined;

/** The app-wide chat room controller — created once, then reused across mounts. */
export function mainChat(): MainChat {
  if (_mainChat) return _mainChat;
  return (_mainChat = createRoot(() => {
    const [currentId, setCurrentId] = createSignal<string | null>(null);
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
        // Same lockstep: the in-flight run of the loaded thread, for a cold-read
        // reattach (a page reload mid-stream).
        activeRun: () => (session.loading ? undefined : session()?.activeRun),
        // Same lockstep: the loaded thread's git-style snapshot history.
        initialSnapshots: () =>
          session.loading ? undefined : session()?.snapshots,
      },
    );
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
    // Same main-room-only mirror for the last-run-error echo, so the favicon can flag a
    // failed run from any screen.
    createEffect(() => setRunErrored(stream.errored()));
    const [warmResolved, setWarmResolved] = createSignal(false);
    return {
      currentId,
      setCurrentId,
      stream,
      warmResolved,
      markWarmResolved: () => setWarmResolved(true),
    } satisfies MainChat;
  }));
}
