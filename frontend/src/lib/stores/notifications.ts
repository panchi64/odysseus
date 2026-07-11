/**
 * Global notification store — the attention/notification surface's frontend
 * half. A separate surface from the chat/run stream: it never touches the
 * per-run event union, and it lives for the app's session rather than one
 * conversation.
 *
 * Backend-owned: read/unread policy, emit policy, and dedupe policy all live
 * server-side (`docs` notification design). This store only mirrors what the
 * backend reports — REST backfill on (re)connect, then live `notification.*`
 * SSE events merged on top — and relays intent (mark-read) back.
 *
 * Lifecycle: `startNotifications()` after the session is authenticated,
 * `stopNotifications()` on logout/lock (see `~/app/AppShell.tsx`, which hooks
 * the same `useSession()` signal the auth guard uses). A module-level
 * singleton, like `chatActivity`/`connectivity` — there is exactly one
 * operator, so exactly one notification feed.
 */
import { createSignal } from "solid-js";
import { api } from "~/lib/api";
import { getToken } from "~/lib/api/token";
import {
  streamNotifications,
  type NotificationStreamState,
} from "~/lib/stream/notificationStream";
import type {
  Notification,
  NotificationsPage,
  NotificationStreamEvent,
} from "~/lib/stream/notificationEvents";

/** How many most-recent notifications to backfill on connect. The bell/panel
 *  UI (next batch) can page further back via `before`; this store only ever
 *  holds the live head. */
const BACKFILL_LIMIT = 50;

const [items, setItems] = createSignal<Notification[]>([]);
const [unreadCount, setUnreadCount] = createSignal(0);
const [connectionState, setConnectionState] = createSignal<
  NotificationStreamState | "idle"
>("idle");

let controller: AbortController | null = null;
let running = false;

// Backfill (REST) and the live stream connect concurrently so there's no gap
// between "as of the backfill query" and "first live event" — but that means
// stream events can arrive mid-flight, before we know the backfill's baseline
// unreadCount. Buffer them while a hydrate is in flight and replay them
// through the normal merge path once it lands, instead of racing two writers
// against `unreadCount`.
let hydrating = false;
let buffered: NotificationStreamEvent[] = [];

// Bumped on every start/stop so a hydrate() from a torn-down session can never
// write into a newer (or the stopped) session's state — belt-and-braces with
// the AbortSignal below: the signal usually cuts the fetch off outright, but a
// response that lands in the same tick as a stop/restart is still guarded by
// the generation check before any store write.
let generation = 0;

/** Upsert one notification by id — the same merge for both a fresh `created`
 *  and an `updated` (an update for an id already held just replaces it in
 *  place; a `created` that dupes an id already backfilled is a no-op replace,
 *  covering replay/backfill overlap). Adjusts `unreadCount` only on an actual
 *  read-state transition so re-applying the same notification twice can't
 *  double-count. */
function upsert(notification: Notification): void {
  const prev = items();
  const idx = prev.findIndex((n) => n.id === notification.id);
  if (idx === -1) {
    setItems([notification, ...prev]);
    if (!notification.readAt) setUnreadCount((c) => c + 1);
    return;
  }
  const was = prev[idx];
  if (!was.readAt && notification.readAt) {
    setUnreadCount((c) => Math.max(0, c - 1));
  } else if (was.readAt && !notification.readAt) {
    setUnreadCount((c) => c + 1);
  }
  const next = prev.slice();
  next[idx] = notification;
  setItems(next);
}

function applyStreamEvent(event: NotificationStreamEvent): void {
  upsert(event.notification);
}

function handleStreamEvent(event: NotificationStreamEvent): void {
  if (hydrating) {
    buffered.push(event);
    return;
  }
  applyStreamEvent(event);
}

/** `gen` pins this call to the session that started it; `signal` ties the
 *  request to that session's AbortController so a stop() cuts it off outright.
 *  Both the success write and the finally's hydrating/buffered bookkeeping
 *  re-check `gen` against the current `generation` — a session that's since
 *  been torn down (or superseded by a new start) never touches live state. */
async function hydrate(gen: number, signal: AbortSignal): Promise<void> {
  hydrating = true;
  try {
    const page = await api.get<NotificationsPage>(
      `/notifications?limit=${BACKFILL_LIMIT}`,
      { signal },
    );
    if (gen !== generation) return; // superseded — a newer session owns the store now
    setItems(page.items);
    setUnreadCount(page.unreadCount);
  } catch {
    /* best effort — the live stream still delivers new notifications; the
     * next reconnect (or an explicit re-hydrate) retries the backfill. */
  } finally {
    if (gen !== generation) return; // don't clobber a newer session's hydrating/buffered
    hydrating = false;
    const pending = buffered;
    buffered = [];
    for (const event of pending) applyStreamEvent(event);
  }
}

/** Start the live feed. Idempotent — safe to call from an effect that may
 *  re-fire while already running. No-op without a token (nothing to
 *  authenticate the stream with; `startNotifications` is meant to be called
 *  only once authenticated anyway). */
export function startNotifications(): void {
  if (running || !getToken()) return;
  running = true;
  generation += 1;
  const gen = generation;
  const ac = new AbortController();
  controller = ac;
  setConnectionState("connecting");
  void streamNotifications({
    signal: ac.signal,
    onEvent: handleStreamEvent,
    onStateChange: setConnectionState,
  });
  void hydrate(gen, ac.signal);
}

/** Tear down the live feed and clear all state — logout/lock leaves nothing
 *  of the previous operator's notifications behind. Bumping `generation`
 *  invalidates any hydrate() still in flight (belt-and-braces alongside the
 *  abort — see `hydrate`'s doc comment) even if a response lands before its
 *  abort is observed. */
export function stopNotifications(): void {
  running = false;
  generation += 1;
  controller?.abort();
  controller = null;
  hydrating = false;
  buffered = [];
  setItems([]);
  setUnreadCount(0);
  setConnectionState("idle");
}

/** Mark specific notifications read — optimistic, reconciled by the
 *  `notification.updated` events the backend fans out once it processes the
 *  request (which land through the normal `upsert` merge, so they're a no-op
 *  if the optimistic state already matches). Rolled back on failure. */
export async function markRead(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const idSet = new Set(ids);
  const prev = items();
  const now = new Date().toISOString();
  let delta = 0;
  setItems(
    prev.map((n) => {
      if (!idSet.has(n.id) || n.readAt) return n;
      delta += 1;
      return { ...n, readAt: now };
    }),
  );
  if (delta > 0) setUnreadCount((c) => Math.max(0, c - delta));
  try {
    await api.post("/notifications/read", { ids });
  } catch {
    setItems(prev);
    if (delta > 0) setUnreadCount((c) => c + delta);
  }
}

/** Mark every currently-known unread notification read. */
export async function markAllRead(): Promise<void> {
  const prev = items();
  const unreadIds = prev.filter((n) => !n.readAt).map((n) => n.id);
  if (unreadIds.length === 0) return;
  const now = new Date().toISOString();
  setItems(prev.map((n) => (n.readAt ? n : { ...n, readAt: now })));
  setUnreadCount(0);
  try {
    await api.post("/notifications/read_all");
  } catch {
    setItems(prev);
    setUnreadCount(unreadIds.length);
  }
}

/** Mark a conversation's unread notifications read — the read-on-view policy
 *  (opening a conversation resolves its unread run and approval items) calls
 *  this from the chat screen. */
export function markConversationRead(conversationId: string): void {
  const ids = items()
    .filter((n) => n.conversationId === conversationId && !n.readAt)
    .map((n) => n.id);
  void markRead(ids);
}

export function useNotifications() {
  return {
    get items(): Notification[] {
      return items();
    },
    get unreadCount(): number {
      return unreadCount();
    },
    get connectionState(): NotificationStreamState | "idle" {
      return connectionState();
    },
    markRead,
    markAllRead,
    markConversationRead,
  };
}
