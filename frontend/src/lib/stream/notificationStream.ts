/**
 * Consume the app-lifetime notification Server-Sent Events stream
 * (`GET /notifications/stream`).
 *
 * A sibling to `./runStream.ts`, not a shared implementation — see that file's
 * CLAUDE.md note. It copies the proven transport shape (fetch + body reader for
 * a bearer header and `Last-Event-ID`, exponential backoff, a read-timeout
 * watchdog tolerant of the backend's keepalive comment) but deliberately
 * diverges in one way: this stream has **no give-up budget**. It is subscribed
 * once for the app's lifetime (see `~/lib/stores/notifications`), so a
 * transport that can't be revived should keep trying rather than surface a
 * "detached" state — there's no per-run UI waiting on it. It also re-kicks the
 * backoff wait early on `online`/`visibilitychange` (tab foregrounded), so a
 * laptop that slept through a backend restart reconnects the moment it's
 * plausible rather than waiting out the last scheduled delay.
 *
 * `runStream.ts` has no tests to extract against safely, so this is a
 * conservative copy rather than a shared-helper refactor — see frontend
 * CLAUDE.md / stream CLAUDE.md for the followup note if that changes.
 */
import { API_BASE } from "~/lib/config";
import { getToken } from "~/lib/api/token";
import { handleAuthFailure } from "~/lib/api/client";
import { setBackendReachable } from "~/lib/stores/connectivity";
import type { NotificationStreamEvent } from "./notificationEvents";

export type NotificationStreamState = "connecting" | "open" | "reconnecting";

export interface NotificationStreamOptions {
  onEvent: (event: NotificationStreamEvent) => void;
  /** Fired on every transport state transition — lets the store surface a
   *  connection indicator without duplicating this module's state machine. */
  onStateChange?: (state: NotificationStreamState) => void;
  signal?: AbortSignal;
  /** Resume from after this seq (e.g. when re-subscribing after a reload with
   *  a remembered high-water mark). */
  fromSeq?: number;
}

const RECONNECT_BASE_DELAY_MS = 500;
const RECONNECT_MAX_DELAY_MS = 10_000;
// Read timeout: the backend flushes a keepalive comment every ~15s (same
// transport discipline as the run stream); comfortably above that to avoid
// false trips from a merely-quiet stream.
const READ_TIMEOUT_MS = 30_000;

/** Like `runStream.ts`'s `delay`, but also resolves early on `online` or the
 *  tab becoming visible — a deliberate re-kick so a backgrounded/offline tab
 *  reconnects promptly once it's plausible again, instead of waiting out
 *  whatever backoff step it was mid-delay on. Still resolves (never rejects)
 *  on abort, matching the run-stream helper's contract. */
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      window.removeEventListener("online", finish);
      document.removeEventListener("visibilitychange", onVisible);
      signal?.removeEventListener("abort", finish);
      resolve();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") finish();
    };
    const timer = setTimeout(finish, ms);
    window.addEventListener("online", finish);
    document.addEventListener("visibilitychange", onVisible);
    signal?.addEventListener("abort", finish);
  });
}

/** Parse one SSE frame (the lines between blank lines) into an event. */
function parseFrame(frame: string): NotificationStreamEvent | null {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as NotificationStreamEvent;
  } catch {
    return null;
  }
}

/** Stream notifications until aborted or the token disappears (logout/lock —
 *  nothing left to authenticate the stream with). Retries forever otherwise;
 *  there is no reconnect budget and no "detached" terminal state. */
export async function streamNotifications(
  options: NotificationStreamOptions,
): Promise<void> {
  const { onEvent, onStateChange, signal, fromSeq } = options;
  let lastSeq: number | null = fromSeq ?? null;
  let failures = 0;
  // Tracks "has this stream ever reached open", independent of `failures`
  // (which resets on every parsed frame for backoff purposes). A watchdog
  // break with no thrown error resets `failures` to 0 on its last frame, so
  // basing the "connecting" vs "reconnecting" label on `failures` alone would
  // mislabel that reconnect as a fresh "connecting" attempt.
  let hasConnectedOnce = false;

  while (!signal?.aborted) {
    if (!getToken()) return; // no session to authenticate the stream with

    onStateChange?.(hasConnectedOnce ? "reconnecting" : "connecting");
    try {
      const headers: Record<string, string> = {
        Accept: "text/event-stream",
        Authorization: `Bearer ${getToken()}`,
      };
      if (lastSeq != null) headers["Last-Event-ID"] = String(lastSeq);

      const res = await fetch(`${API_BASE}/notifications/stream`, {
        headers,
        credentials: "omit",
        signal,
      });
      if (res.status === 401 || res.status === 423) {
        // Session expiry / vault re-lock — not a transport hiccup. Route
        // through the same expiry path the REST client and run stream use,
        // then stop: retrying can't succeed without a fresh token.
        handleAuthFailure();
        return;
      }
      if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);
      setBackendReachable(true);
      hasConnectedOnce = true;
      onStateChange?.("open");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const result = await Promise.race([
          reader.read(),
          new Promise<"timeout">((resolve) => {
            timer = setTimeout(() => resolve("timeout"), READ_TIMEOUT_MS);
          }),
        ]).finally(() => clearTimeout(timer));
        if (result === "timeout") {
          // Dead connection — drop it and reconnect from lastSeq (replays the gap).
          await reader.cancel().catch(() => {});
          break;
        }
        const { value, done } = result;
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const event = parseFrame(frame);
          if (!event) continue;
          failures = 0; // a real frame resets the reconnect budget
          lastSeq = event.seq;
          onEvent(event);
        }
      }
      // Body ended (dropped or watchdog-cancelled) — loop reconnects from
      // lastSeq. There is no terminal event on this stream; it only ends via
      // abort or a vanished token.
    } catch {
      if (signal?.aborted) return;
      setBackendReachable(false); // a live stream error means the backend went unreachable
      const backoff = Math.min(
        RECONNECT_BASE_DELAY_MS * 2 ** failures,
        RECONNECT_MAX_DELAY_MS,
      );
      failures += 1;
      onStateChange?.("reconnecting");
      await delay(backoff, signal);
    }
  }
}
