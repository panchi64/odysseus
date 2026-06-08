import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import type { ChatMessage, ChatSession, ChatSummary } from "./model";
import {
  mockModels,
  mockSession,
  mockSessions,
  mockStreamingReply,
} from "./mocks";

/* ── localStorage helpers (best-effort, SSR/permission safe) ──────────────── */

function readLS(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLS(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

/* ── Recency-gated resume ─────────────────────────────────────────────────────
   On entry the chat resumes the last conversation only while it's still "warm"
   (last activity within the window); otherwise it opens a fresh composer. This
   keeps a mid-task return seamless without dumping a stale thread on everyone
   else. */

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

/* ── Selected model (sticky across surfaces) ──────────────────────────────── */

const MODEL_KEY = "ody.chat.model";
const [_model, _setModel] = createSignal<string>(
  readLS(MODEL_KEY) ?? mockModels[0].value,
);
export const selectedModel = _model;
export function setSelectedModel(model: string): void {
  _setModel(model);
  writeLS(MODEL_KEY, model);
}
export function modelOptions() {
  return mockModels;
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
   The overview launchpad hands the chat screen what to do on arrival: start a
   new conversation seeded with a typed message, or open a specific thread. Both
   are one-shot and consumed by the chat screen on mount. */

const [_pendingDraft, _setPendingDraft] = createSignal<{
  text: string;
  model: string;
} | null>(null);

/** Begin a new conversation with `text` (used by the overview composer). */
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
/** Request that the chat screen open a specific existing thread on arrival. */
export function openConversation(id: string): void {
  _setRequestedSession(id);
}
export function consumeRequestedSession(): string | null {
  const v = _requestedSession();
  if (v) _setRequestedSession(null);
  return v;
}

/* ── Mutable session list (Phase-1 local state) ──────────────────────────── */

/** Writable signal so UI can remove or mutate session summaries optimistically. */
const [_sessions, _setSessions] = createSignal<ChatSummary[]>(mockSessions);

/* ── Read accessors (the seam) ───────────────────────────────────────────────
   Phase 1: resolve from fixtures. Phase 2: swap the bodies for api calls in
   ~/lib/api — the return types are unchanged, so screens don't change. */

async function fetchSessions(): Promise<ChatSummary[]> {
  return _sessions();
}

async function fetchSession(_id: string): Promise<ChatSession> {
  return mockSession;
}

export function useChatSessions(): Resource<ChatSummary[]> {
  const [data] = createResource(_sessions, fetchSessions);
  return data;
}

/** Loads a session. A null/empty id means a new, unsaved conversation — the
 *  resource simply doesn't fetch, so the screen renders an empty thread. */
export function useChatSession(id: () => string | null): Resource<ChatSession> {
  const [data] = createResource(id, fetchSession);
  return data;
}

/* ── Streaming controller ────────────────────────────────────────────────────
   Drives the live message list. Today a mock generator reveals reasoning, a
   tool call, then answer tokens so every streaming state is visible. Phase 2
   replaces the generator with a subscription from ~/lib/stream; the store shape
   and `send` signature stay the same. */

let counter = 0;
const nextId = (prefix: string) => `${prefix}-live-${++counter}`;

export function createChatStream(
  initial: () => ChatMessage[] | undefined,
  key: () => string | null = () => null,
) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  const [sending, setSending] = createSignal(false);
  const timers: ReturnType<typeof setTimeout>[] = [];
  const clearTimers = () => {
    timers.forEach(clearTimeout);
    timers.length = 0;
  };
  const after = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

  // Re-seed whenever the conversation changes — keyed on session identity, not
  // just the message-array reference. Phase-1 fetches share a fixture reference,
  // so a ref check alone would miss an existing→existing switch and leave the
  // previous thread's live messages on screen.
  const INIT = Symbol("init");
  let lastKey: string | null | typeof INIT = INIT;
  let lastSource: ChatMessage[] | undefined | typeof INIT = INIT;
  createEffect(() => {
    const k = key();
    const source = initial();
    if (k === lastKey && source === lastSource) return;
    lastKey = k;
    lastSource = source;
    clearTimers();
    setSending(false);
    setMessages(reconcile(source ? source.slice() : []));
  });

  function send(text: string) {
    if (!text.trim() || sending()) return;
    setSending(true);

    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
    };
    const assistantId = nextId("a");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      model: selectedModel(),
      content: "",
      streaming: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(produce((m) => m.push(userMsg, assistantMsg)));

    const idx = () => messages.findIndex((m) => m.id === assistantId);
    const patch = (fn: (m: ChatMessage) => void) => {
      // The message may be gone if the store was reset mid-stream — skip safely.
      const i = idx();
      if (i < 0) return;
      setMessages(produce((m) => fn(m[i])));
    };

    // 1) reasoning appears
    after(250, () =>
      patch((m) => (m.reasoning = mockStreamingReply.reasoning)),
    );

    // 2) tool call: running -> ok
    after(500, () =>
      patch((m) => {
        m.tools = [
          {
            id: nextId("t"),
            name: mockStreamingReply.tools[0].name,
            args: mockStreamingReply.tools[0].args,
            status: "running",
          },
        ];
      }),
    );
    after(1600, () =>
      patch((m) => {
        if (m.tools?.[0]) {
          m.tools[0].status = "ok";
          m.tools[0].result = mockStreamingReply.tools[0].result;
          m.tools[0].elapsedMs = mockStreamingReply.tools[0].elapsedMs;
        }
      }),
    );

    // 3) answer streams token-by-token
    const words = mockStreamingReply.content.split(" ");
    words.forEach((_word, i) =>
      after(1900 + i * 28, () =>
        patch((m) => (m.content = words.slice(0, i + 1).join(" "))),
      ),
    );

    // 4) done
    after(1900 + words.length * 28 + 60, () => {
      patch((m) => (m.streaming = false));
      setSending(false);
    });
  }

  function deleteLastMessage(): ChatMessage | undefined {
    const last = messages[messages.length - 1];
    if (!last) return undefined;
    setMessages(produce((m) => m.pop()));
    return last;
  }

  function restoreMessage(msg: ChatMessage) {
    setMessages(produce((m) => m.push(msg)));
  }

  function clearMessages(): ChatMessage[] {
    const snapshot = messages.slice();
    setMessages(reconcile([]));
    return snapshot;
  }

  function restoreMessages(snapshot: ChatMessage[]) {
    setMessages(reconcile(snapshot));
  }

  onCleanup(clearTimers);

  return {
    messages,
    sending,
    send,
    deleteLastMessage,
    restoreMessage,
    clearMessages,
    restoreMessages,
  };
}
