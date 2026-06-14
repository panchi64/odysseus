import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Accessor,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api } from "~/lib/api";
import { readLS, writeLS } from "~/lib/storage";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import { streamRun, type RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import type {
  ApprovalDecision,
  ArtifactRef,
  AssistantBlock,
  ChatMessage,
  ChatSession,
  ChatSummary,
  HostCommand,
  HostCommandBlock,
  HostCommandPhase,
  PreviewBlock,
  ToolBlock,
  ToolInvocation,
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

const [_pendingDraft, _setPendingDraft] = createSignal<{
  text: string;
  model: ModelSelection | null;
} | null>(null);

export function startConversation(
  text: string,
  model: ModelSelection | null,
): void {
  _setPendingDraft({ text, model });
}
export function consumePendingDraft(): {
  text: string;
  model: ModelSelection | null;
} | null {
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

interface ArtifactDTO {
  artifact_id: string;
  title: string;
  filename: string;
  content_type: string;
  kind: ArtifactRef["kind"];
}

interface MessageDTO {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string | null;
  tools: ToolCallDTO[];
  artifacts?: ArtifactDTO[];
  created_at?: string | null;
  /** The model that produced this assistant turn. */
  model?: string | null;
  /** 0-based index of this turn among its sibling versions. */
  version_index?: number;
  /** Total sibling versions for this turn (≥1). */
  version_count?: number;
  /** Whether the operator has pinned this turn. */
  pinned?: boolean;
}

interface ConversationDetailDTO extends ConversationSummaryDTO {
  messages: MessageDTO[];
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

/** Map a published-artifact DTO/event to the seam type. Shared by the cold read
 *  (history detail) and the warm stream (`artifact.published`) so both render
 *  identically. */
function toArtifactRef(dto: ArtifactDTO): ArtifactRef {
  return {
    artifactId: dto.artifact_id,
    title: dto.title,
    filename: dto.filename,
    contentType: dto.content_type,
    kind: dto.kind,
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
  for (const a of dto.artifacts ?? [])
    blocks.push({
      kind: "artifact",
      id: `${dto.id}-${a.artifact_id}`,
      artifact: toArtifactRef(a),
    });
  if (dto.content)
    blocks.push({ kind: "text", id: `${dto.id}-text`, text: dto.content });
  // The answer lives in the text block(s); keep `content` empty for assistant
  // turns so it isn't a second, divergent copy of the same text.
  return { ...base, content: "", blocks, model: dto.model ?? undefined };
}

/* ── Read accessors (the seam) ────────────────────────────────────────────── */

let refetchSessions: (() => void) | undefined;

async function fetchSessions(): Promise<ChatSummary[]> {
  const rows = await api.get<ConversationSummaryDTO[]>("/conversations");
  return rows.map(toSummary);
}

export function useChatSessions(): Accessor<ChatSummary[] | undefined> {
  const [data, { refetch }] = createResource(fetchSessions);
  refetchSessions = refetch;
  // Read `.latest`, not the resource itself. `refreshSessions()` runs after every
  // turn and refetches in place; reading the resource under the app's
  // fallback-less root <Suspense> would re-suspend it for the duration of each
  // refetch, blanking the whole page for a frame. `.latest` keeps the prior list
  // on screen while the refetch is in flight, so a finishing stream no longer
  // flickers the page.
  return () => data.latest;
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
  };
}

/** Loads a session. A null id means a new, unsaved conversation — the resource
 *  doesn't fetch, so the screen renders an empty thread. */
export function useChatSession(id: () => string | null): Resource<ChatSession> {
  const [data] = createResource(id, fetchSession);
  return data;
}

export async function renameConversation(
  id: string,
  title: string,
): Promise<void> {
  await api.patch(`/conversations/${id}`, { title });
  refreshSessions();
}

export async function deleteConversation(id: string): Promise<void> {
  await api.del(`/conversations/${id}`);
  refreshSessions();
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
}

export function createChatStream(
  initial: () => ChatMessage[] | undefined,
  key: () => string | null = () => null,
  options: ChatStreamOptions = {},
) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  const [sending, setSending] = createSignal(false);
  let controller: AbortController | null = null;
  // The run currently streaming, if any — needed to cancel it on the backend
  // (aborting the SSE alone leaves the run executing server-side).
  let activeRunId: string | null = null;
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
    setSending(false);
    activeConversationId = k;
    // A null key is a new, unsaved conversation: it has no persisted history, so
    // the only `source` here is the seam resource's *retained* value from the
    // thread we just left (Solid keeps a resource's last value once its id goes
    // null). Seeding from it would keep a just-deleted thread's messages on
    // screen, so a null key always starts empty.
    const seed = k === null ? [] : source ? source.slice() : [];
    setMessages(reconcile(seed));
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
      case "artifact.published":
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "artifact",
            id: `artifact-${ev.artifact_id}`,
            artifact: toArtifactRef(ev),
          });
        });
        break;
      case "preview.ready":
        // At most one live preview per turn — a later ready replaces the prior.
        patchById(assistantId, (m) => {
          const preview = { url: ev.url, title: ev.title ?? undefined };
          const existing = m.blocks?.find(
            (b): b is PreviewBlock => b.kind === "preview",
          );
          if (existing) existing.preview = preview;
          else
            (m.blocks ?? (m.blocks = [])).push({
              kind: "preview",
              id: nextId("preview"),
              preview,
            });
        });
        break;
      case "preview.stopped":
        patchById(assistantId, (m) => {
          if (m.blocks) m.blocks = m.blocks.filter((b) => b.kind !== "preview");
        });
        break;
      case "conversation.titled":
        // Conversation-level, not message-level: hand it to the typewriter reveal
        // rather than folding onto the assistant message.
        revealTitle(ev.conversation_id, ev.title);
        break;
      case "run.error":
        toast.error(ev.message || "The run failed.");
        patchById(assistantId, (m) => (m.streaming = false));
        break;
      // run.started / run.ended / step.* / run.metrics / limit.notice: no store change
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
  ): Promise<void> {
    activeRunId = runId;
    patchById(assistantId, (m) => (m.runId = runId));
    try {
      controller = new AbortController();
      await streamRun(runId, {
        signal: controller.signal,
        onEvent: (ev) => foldEvent(assistantId, ev),
      });
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to reach the assistant.",
      );
    } finally {
      activeRunId = null;
      patchById(assistantId, (m) => (m.streaming = false));
      setSending(false);
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

  /** Reconcile the live store with the backend's projected active path after a
   *  turn: adopt each turn's real node id + version index/count + pin by position
   *  (the store mirrors the same active path), leaving live-only fields the cold
   *  projection doesn't carry — `preview`, `runId` — untouched. A length mismatch
   *  (e.g. a turn that produced no persisted answer) falls back to a full reseat.
   *  Best-effort: a failed read leaves the optimistic store in place. */
  async function adoptServerMeta(): Promise<void> {
    if (activeConversationId === null) return;
    let detail: ConversationDetailDTO;
    try {
      detail = await api.get<ConversationDetailDTO>(
        `/conversations/${activeConversationId}`,
      );
    } catch {
      return;
    }
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

  async function send(text: string): Promise<void> {
    if (!text.trim() || sending()) return;
    setSending(true);

    const wasNew = activeConversationId === null;
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
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
  ): Promise<void> {
    if (activeConversationId === null || sending() || !newText.trim()) return;
    const j = messages.findIndex(
      (m) => m.id === messageId && m.role === "user",
    );
    if (j < 0) return;
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
      });
      const editedUser: ChatMessage = { ...messages[j], content: prompt };
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
  async function removeMessage(messageId: string): Promise<void> {
    if (activeConversationId === null) return;
    if (sending()) await cancel();
    try {
      const detail = await api.del<ConversationDetailDTO>(
        `/conversations/${activeConversationId}/messages/${messageId}`,
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

  onCleanup(() => controller?.abort());

  return {
    messages,
    sending,
    send,
    cancel,
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
