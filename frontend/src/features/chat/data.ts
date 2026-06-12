import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api } from "~/lib/api";
import { readLS, writeLS } from "~/lib/storage";
import { effectiveSelection } from "~/lib/stores/models";
import { streamRun, type RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import type {
  ApprovalDecision,
  ArtifactRef,
  ChatMessage,
  ChatSession,
  ChatSummary,
  HostCommand,
  HostCommandPhase,
  ToolInvocation,
} from "./model";

/** The one approval-gated tool that runs on the real host (vs. the sandbox). Its
 *  approval + execution render as a single persistent terminal, never a generic
 *  approval card or tool card. */
export const HOST_COMMAND_TOOL = "run_host_command";

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

/* ── Cross-surface entry intents ──────────────────────────────────────────────
   The overview launchpad hands the chat screen what to do on arrival. */

const [_pendingDraft, _setPendingDraft] = createSignal<{
  text: string;
  model: string;
} | null>(null);

export function startConversation(text: string, model: string): void {
  _setPendingDraft({ text, model });
}
export function consumePendingDraft(): { text: string; model: string } | null {
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
  // Host commands render as their own terminal, so split them out of the generic
  // tool-call list (both surfaces come from the same persisted tool calls).
  const tools: ToolInvocation[] = [];
  const hostCommands: HostCommand[] = [];
  for (const t of dto.tools) {
    if (t.name === HOST_COMMAND_TOOL) hostCommands.push(toHostCommand(t));
    else tools.push(toTool(t));
  }
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    reasoning: dto.reasoning ?? undefined,
    tools,
    hostCommands: hostCommands.length ? hostCommands : undefined,
    artifacts: dto.artifacts?.map(toArtifactRef),
    createdAt: dto.created_at ?? new Date().toISOString(),
  };
}

/* ── Read accessors (the seam) ────────────────────────────────────────────── */

const [_sessionsTick, _setSessionsTick] = createSignal(0);

async function fetchSessions(): Promise<ChatSummary[]> {
  const rows = await api.get<ConversationSummaryDTO[]>("/conversations");
  return rows.map(toSummary);
}

export function useChatSessions(): Resource<ChatSummary[]> {
  const [data] = createResource(_sessionsTick, fetchSessions);
  return data;
}

/** Re-read the conversation list (after a turn, rename, or delete). */
export function refreshSessions(): void {
  _setSessionsTick((t) => t + 1);
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
}

export function createChatStream(
  initial: () => ChatMessage[] | undefined,
  key: () => string | null = () => null,
  options: ChatStreamOptions = {},
) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  const [sending, setSending] = createSignal(false);
  let controller: AbortController | null = null;
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
    // The live store is authoritative for the thread we're already on: never let
    // a (re)fetch of its server history clobber it. This keeps a freshly-created
    // thread's streamed messages — including live-only fields the history
    // projection doesn't carry (preview, artifacts, runId) — when it adopts its
    // backend id, and avoids an empty flash while that history loads.
    if (k === activeConversationId && messages.length > 0) return;
    lastKey = k;
    lastSource = source;
    controller?.abort();
    controller = null;
    setSending(false);
    activeConversationId = k;
    setMessages(reconcile(source ? source.slice() : []));
  });

  function patchById(id: string, fn: (m: ChatMessage) => void): void {
    const i = messages.findIndex((m) => m.id === id);
    if (i < 0) return;
    setMessages(produce((m) => fn(m[i])));
  }

  /** Upsert a host command onto a message, keyed by its tool_call_id. The
   *  `tool.started`, `approval.required`, and `tool.completed` events for the
   *  same host call all land here, each filling in the part it carries. */
  function upsertHostCommand(
    m: ChatMessage,
    toolCallId: string,
    patch: Partial<HostCommand>,
  ): void {
    const list = m.hostCommands ?? (m.hostCommands = []);
    const existing = list.find((h) => h.toolCallId === toolCallId);
    if (existing) Object.assign(existing, patch);
    else list.push({ toolCallId, command: "", phase: "pending", ...patch });
  }

  function foldEvent(assistantId: string, ev: RunEvent): void {
    switch (ev.type) {
      case "thinking.delta":
        patchById(
          assistantId,
          (m) => (m.reasoning = (m.reasoning ?? "") + ev.text),
        );
        break;
      case "answer.delta":
        patchById(assistantId, (m) => (m.content += ev.text));
        break;
      case "tool.started":
        // Host commands are terminals, not generic tool cards. (tool.started
        // fires before approval.required, so this seeds the pending terminal.)
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHostCommand(m, ev.tool_call_id, {
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
          m.tools = [
            ...(m.tools ?? []),
            {
              id: ev.tool_call_id,
              name: ev.name,
              args: formatArgs(ev.args),
              status: "running",
            },
          ];
        });
        break;
      case "tool.completed":
        if (ev.name === HOST_COMMAND_TOOL) {
          const r = parseHostResult(ev.result);
          if (r) {
            patchById(assistantId, (m) =>
              upsertHostCommand(m, ev.tool_call_id, {
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
          const t = m.tools?.find((x) => x.id === ev.tool_call_id);
          if (t) {
            t.status = "ok";
            t.result = stringifyResult(ev.result);
          }
        });
        break;
      case "tool.failed":
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHostCommand(m, ev.tool_call_id, {
              phase: "error",
              error: ev.error,
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          const t = m.tools?.find((x) => x.id === ev.tool_call_id);
          if (t) {
            t.status = "error";
            t.error = ev.error;
          }
        });
        break;
      case "approval.required":
        if (ev.name === HOST_COMMAND_TOOL) {
          patchById(assistantId, (m) =>
            upsertHostCommand(m, ev.tool_call_id, {
              command:
                typeof ev.args.command === "string" ? ev.args.command : "",
              explanation: ev.explanation ?? undefined,
              phase: "pending",
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          m.approvals = [
            ...(m.approvals ?? []),
            {
              toolCallId: ev.tool_call_id,
              name: ev.name,
              args: ev.args,
              summary: ev.summary,
              explanation: ev.explanation ?? undefined,
            },
          ];
        });
        break;
      case "artifact.published":
        patchById(assistantId, (m) => {
          m.artifacts = [...(m.artifacts ?? []), toArtifactRef(ev)];
        });
        break;
      case "preview.ready":
        patchById(assistantId, (m) => {
          m.preview = { url: ev.url, title: ev.title ?? undefined };
        });
        break;
      case "preview.stopped":
        patchById(assistantId, (m) => (m.preview = null));
        break;
      case "run.error":
        toast.error(ev.message || "The run failed.");
        patchById(assistantId, (m) => (m.streaming = false));
        break;
      // run.started / run.ended / step.* / run.metrics / limit.notice: no store change
    }
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
    const selection = effectiveSelection();
    const assistantId = nextId("a");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      model: selection?.model,
      content: "",
      streaming: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(produce((m) => m.push(userMsg, assistantMsg)));

    try {
      const created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId ?? undefined,
        endpoint_id: selection?.endpointId,
        model: selection?.model,
      });
      activeConversationId = created.conversation_id;
      patchById(assistantId, (m) => (m.runId = created.run_id));

      controller = new AbortController();
      await streamRun(created.run_id, {
        signal: controller.signal,
        onEvent: (ev) => foldEvent(assistantId, ev),
      });
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to reach the assistant.",
      );
    } finally {
      patchById(assistantId, (m) => (m.streaming = false));
      setSending(false);
      if (wasNew && activeConversationId) {
        options.onConversationStarted?.(activeConversationId);
      }
      options.onTurnComplete?.();
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
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to submit the decision.",
      );
    }
  }

  /** Decide a message's pending approvals; the cards clear once submitted. */
  const resolveApproval = (messageId: string, decisions: ApprovalDecision[]) =>
    submitDecisions(messageId, decisions, (m) => (m.approvals = []));

  /** Decide a message's host-command approvals. Approved commands begin running
   *  and denied ones close out optimistically; the stream confirms the outcome. */
  const resolveHostCommands = (
    messageId: string,
    decisions: ApprovalDecision[],
  ) =>
    submitDecisions(messageId, decisions, (m) => {
      for (const d of decisions) {
        const h = m.hostCommands?.find((x) => x.toolCallId === d.tool_call_id);
        if (h) h.phase = d.approved ? "running" : "denied";
      }
    });

  onCleanup(() => controller?.abort());

  return { messages, sending, send, resolveApproval, resolveHostCommands };
}
