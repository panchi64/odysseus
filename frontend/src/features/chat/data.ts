import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import type { ChatMessage, ChatSession, ChatSummary } from "./model";
import { mockSession, mockSessions, mockStreamingReply } from "./mocks";

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

export function useChatSession(id: () => string): Resource<ChatSession> {
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

export function createChatStream(initial: () => ChatMessage[] | undefined) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  const [sending, setSending] = createSignal(false);
  const timers: ReturnType<typeof setTimeout>[] = [];
  const after = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

  // Seed once from the (async) source, then let send() drive the list.
  let seeded = false;
  createEffect(() => {
    const source = initial();
    if (!seeded && source) {
      seeded = true;
      setMessages(reconcile(source.slice()));
    }
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
      model: mockSession.model,
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

  onCleanup(() => timers.forEach(clearTimeout));

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
