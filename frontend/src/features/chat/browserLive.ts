/** The agent's live browser, as the panel sees it — pure state, no DOM and no socket.
 *
 *  The backend streams JSON envelopes over a token-gated WebSocket: `frame` messages
 *  carrying a base64 JPEG plus the page's chrome, and one `end` message when the session
 *  is torn down. Everything that decides *what the panel shows* lives here so it can be
 *  tested without mounting a component or opening a socket; `BrowserPanel` owns only the
 *  socket and the markup.
 *
 *  Two things shape the state:
 *
 *  **Frames replace, they don't accumulate.** The panel shows the page now; a backlog
 *  would only make the operator watch the past at a delay. So there is one current frame,
 *  never a list.
 *
 *  **Metadata carries forward.** A frame is allowed to arrive without a URL or title
 *  (the backend refreshes those on its own tick, not per frame). Blanking the readout in
 *  that gap would make the panel flicker between "example.com" and nothing, so an absent
 *  field keeps the last value it had.
 */

/** One decoded frame from the stream, ready to render. */
export interface BrowserFrame {
  /** Base64 JPEG — the panel prefixes the data-URI scheme itself. */
  data: string;
  width: number;
  height: number;
  url: string;
  title: string;
  /** How many tabs the session has open, and which one this frame is of. */
  tabs: number;
  active: number;
}

/** What the panel is doing right now. */
export type BrowserStatus =
  /** A socket is open and frames are expected; `frame` may still be null (first paint). */
  | "streaming"
  /** The session ended — the last frame stays on screen, dimmed, as a still. */
  | "ended"
  /** The socket dropped for a reason that isn't a verdict; a retry is in flight. */
  | "reconnecting";

export interface BrowserLiveState {
  /** The stream socket's path (`/browser/stream/{token}`), or null when there is none. */
  streamPath: string | null;
  frame: BrowserFrame | null;
  status: BrowserStatus;
  /** Operator-facing reason the stream ended, when it did. */
  note: string | null;
}

export const NO_BROWSER: BrowserLiveState = {
  streamPath: null,
  frame: null,
  status: "streaming",
  note: null,
};

/** The `browser.live` announcement (or a `/browser/session` lookup) as panel state.
 *
 *  Re-announcing the *same* session leaves the state alone, so a turn that calls a dozen
 *  browser tools doesn't reset the panel a dozen times; a genuinely new session (a new
 *  token, after a reap) starts clean rather than showing the dead session's last frame
 *  under the new one's URL. */
export function openBrowser(
  state: BrowserLiveState,
  streamPath: string,
): BrowserLiveState {
  if (state.streamPath === streamPath) return state;
  return { streamPath, frame: null, status: "streaming", note: null };
}

/** The session is gone: keep the last frame as a still and say why. */
export function endBrowser(
  state: BrowserLiveState,
  note: string,
): BrowserLiveState {
  return { ...state, status: "ended", note };
}

/** The socket dropped without a verdict — a retry is coming, so the frame stays up. */
export function reconnecting(state: BrowserLiveState): BrowserLiveState {
  return state.status === "ended"
    ? state
    : { ...state, status: "reconnecting", note: null };
}

/** A raw envelope off the socket, before it is known to be well-formed. */
type Envelope = Record<string, unknown>;

/** Fold one socket message into the state.
 *
 *  Unrecognized or malformed messages are ignored rather than thrown on: this is a live
 *  stream, and one bad frame must not take the panel down mid-session. */
export function applyMessage(
  state: BrowserLiveState,
  message: Envelope,
): BrowserLiveState {
  if (message.t === "end") {
    const reason = typeof message.reason === "string" ? message.reason : null;
    return endBrowser(state, endNote(reason));
  }
  if (message.t !== "frame" || typeof message.data !== "string") return state;
  return {
    ...state,
    status: "streaming",
    note: null,
    frame: {
      data: message.data,
      width: numberOr(message.w, state.frame?.width ?? 0),
      height: numberOr(message.h, state.frame?.height ?? 0),
      // Absent metadata keeps the last known value — see the module note.
      url: stringOr(message.url, state.frame?.url ?? ""),
      title: stringOr(message.title, state.frame?.title ?? ""),
      tabs: numberOr(message.tabs, state.frame?.tabs ?? 1),
      active: numberOr(message.active, state.frame?.active ?? 0),
    },
  };
}

/** What to tell the operator when the socket closes, by close code.
 *
 *  4410 and 4404 are the two the panel actually reads apart: one means there *was* a
 *  browser and it is gone (idle-reaped, or evicted), the other that the backend doesn't
 *  know this token at all — usually a restart. Everything else is a dropped connection,
 *  which is not a verdict and reads as one. */
export function closeNote(code: number): string | null {
  if (code === 4410) return "The agent's browser was closed.";
  if (code === 4404) return "This browser session is no longer available.";
  if (code === 1011) return "The browser stream was refused.";
  return null; // not a verdict — the panel retries instead of reporting
}

/** Whether a close code is final, or worth reconnecting after. */
export function isFinal(code: number): boolean {
  return closeNote(code) !== null;
}

function endNote(reason: string | null): string {
  return reason === "stopped"
    ? "The agent's browser was closed."
    : "The browser stream ended.";
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === "string" && value !== "" ? value : fallback;
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** A page URL trimmed for the panel's one-line readout: the host, plus the path when
 *  there is one worth showing. The full URL is the element's `title`, so nothing is lost
 *  — this is only what fits. */
export function displayUrl(url: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    // `about:blank`, `data:…` and `blob:…` all parse, but carry no host — trimming them
    // by this rule would leave "blank", so they are shown as they are.
    if (!parsed.host) return url;
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    return `${parsed.host}${path}${parsed.search}`;
  } catch {
    return url; // not a URL at all — not ours to second-guess
  }
}
