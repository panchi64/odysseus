import {
  createEffect,
  createSignal,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { wsUrl } from "~/lib/config";
import { Button, EmptyState, LoadingText, Panel, Text, Tooltip } from "~/ui";
import {
  applyMessage,
  closeNote,
  displayUrl,
  endBrowser,
  isFinal,
  NO_BROWSER,
  openBrowser,
  reconnecting,
  type BrowserLiveState,
} from "../browserLive";

/** Backoff between reconnect attempts, in ms. A dropped socket is usually a blip (the
 *  backend restarting, a laptop waking), so the first retry is quick; the ceiling keeps
 *  a genuinely dead endpoint from being hammered by a tab left open overnight. */
const RETRY_MS = [500, 1000, 2000, 5000, 10_000];

/**
 * The agent's browser, live — the page it is actually driving, streamed frame by frame.
 *
 * This is deliberately **not** the versioned View panel and shares none of its chrome:
 * no version dropdown, no PREVIEW/CODE tabs, no timeline rail, no download or keeper.
 * There is exactly one thing here to look at and it has no history: a browser is a place
 * the agent *is*, not an artifact it produced.
 *
 * It is a window, not a remote control. Frames come down; nothing goes up. Letting the
 * operator click into the page would put two drivers on one browser, racing each other
 * between the agent's tool calls — and the agent would be acting on a page it had not
 * read. Taking over is a feature that has to be designed, not one to fall into.
 *
 * The session outlives the run that opened it, so its ending has no run stream to ride:
 * the socket's own `end` message is the signal, and a close code tells a reaped session
 * (4410) from one the backend never knew (4404) from an ordinary drop (retry). When it
 * does end, the last frame stays on screen, dimmed — where the agent left the page is
 * usually the thing the operator wanted to see.
 */
export function BrowserPanel(props: {
  /** The stream path (`/browser/stream/{token}`) from `browser.live` or the session
   *  lookup. */
  streamPath: string;
  /** Called when the session is confirmed gone, so the caller drops the panel and the
   *  View takes the slot back. */
  onEnded: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onClose: () => void;
  /** Captures the focusable panel container for the global keymap's focus-jump. */
  panelRef?: (el: HTMLDivElement) => void;
}): JSX.Element {
  const [state, setState] = createSignal<BrowserLiveState>(NO_BROWSER);

  createEffect(() => {
    const path = props.streamPath;
    setState((prev) => openBrowser(prev, path));

    let live = true;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const connect = (): void => {
      if (!live) return;
      socket = new WebSocket(wsUrl(path));
      socket.onopen = () => {
        attempt = 0;
      };
      socket.onmessage = (event) => {
        if (!live || typeof event.data !== "string") return;
        try {
          setState((prev) => applyMessage(prev, JSON.parse(event.data)));
        } catch {
          // One unparseable frame is not worth taking the stream down for.
        }
      };
      socket.onclose = (event) => {
        if (!live) return;
        const note = closeNote(event.code);
        if (note !== null || isFinal(event.code)) {
          setState((prev) =>
            endBrowser(prev, note ?? "The browser stream ended."),
          );
          return;
        }
        // Not a verdict — the last frame stays up while a retry is in flight.
        setState(reconnecting);
        const delay = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)];
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };
    connect();

    onCleanup(() => {
      live = false;
      clearTimeout(timer);
      // `onclose` is cleared first: a deliberate teardown (a thread switch, the panel
      // closing) must not be mistaken for a drop and scheduled for reconnection.
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    });
  });

  // The session ending is what hands the slot back to the View, but only once the
  // operator has had the still frame in front of them — an instant swap would read as
  // the panel glitching rather than as the browser closing.
  createEffect(() => {
    if (state().status !== "ended") return;
    const handoff = setTimeout(props.onEnded, 4000);
    onCleanup(() => clearTimeout(handoff));
  });

  const frame = () => state().frame;
  const pageUrl = () => frame()?.url ?? "";

  return (
    <div
      ref={props.panelRef}
      tabindex={-1}
      /* Matches ViewportPanel: the framed region is the surface, so the breathing
         room comes from here rather than from a card of its own. */
      class="h-full p-2 outline-none transition-colors focus-visible:outline-1 focus-visible:outline-bright"
    >
      <Panel
        label="Browser"
        meta={
          <div class="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              active={props.fullscreen}
              aria-label="Toggle fullscreen"
              aria-pressed={props.fullscreen}
              onClick={props.onToggleFullscreen}
            >
              Expand
            </Button>
            <Tooltip label="Collapse" side="bottom">
              <Button
                variant="ghost"
                size="sm"
                leading="panel-right"
                aria-label="Collapse viewport"
                onClick={props.onClose}
              />
            </Tooltip>
          </div>
        }
        bare
        flush
        fill
        class="h-full"
      >
        <div class="flex h-full min-h-0 flex-col">
          {/* The address readout — the one piece of chrome a browser genuinely needs:
              without it a screenshot of a login page is indistinguishable from a
              screenshot of a phishing page. */}
          <div class="flex items-center gap-2 px-3 py-2">
            {/* The readout is trimmed to fit; the full URL is the hover title, so
                nothing about where the agent actually is gets lost. */}
            <span class="min-w-0 flex-1 truncate" title={pageUrl()}>
              <Text variant="micro" tone="dim">
                {displayUrl(pageUrl()) || "about:blank"}
              </Text>
            </span>
            <Show when={frame() && frame()!.tabs > 1}>
              <Text variant="micro" tone="dim" class="shrink-0">
                TAB {frame()!.active + 1}/{frame()!.tabs}
              </Text>
            </Show>
          </div>

          <div class="relative min-h-0 flex-1">
            <Show
              when={frame()}
              fallback={
                <Show
                  when={state().status === "ended"}
                  fallback={
                    <div class="flex h-full items-center justify-center">
                      <LoadingText label="Waiting for the page…" />
                    </div>
                  }
                >
                  <EmptyState
                    icon="warning"
                    message="The agent's browser is closed"
                    hint={state().note ?? undefined}
                  />
                </Show>
              }
            >
              {(current) => (
                <img
                  /* Centred in the slot, letterboxed rather than cropped: the operator
                     is checking what the agent sees, and a cropped frame hides the part
                     of the page a click landed on. Top-anchoring was tried while the
                     panel was still clamped against the window and could only ever be a
                     narrow column — the leftover height was large enough that splitting
                     it into two bands made the frame read as smaller than it was. Sized
                     against its own row now, the slot fits the frame closely enough that
                     centring is simply where a picture belongs. */
                  class="h-full w-full object-contain transition-opacity"
                  classList={{ "opacity-50": state().status === "ended" }}
                  src={`data:image/jpeg;base64,${current().data}`}
                  alt={
                    frame()?.title
                      ? `The agent's browser, showing ${frame()!.title}`
                      : "The agent's browser"
                  }
                />
              )}
            </Show>

            {/* Non-blocking status strips, mirroring ViewLiveContent: a reconnect or an
                ending is reported over the last frame rather than replacing it. */}
            <Show when={state().status !== "streaming"}>
              <div class="absolute inset-x-0 bottom-0 bg-surface/80 px-3 py-1">
                <Text variant="micro" tone="dim">
                  {state().status === "reconnecting"
                    ? "RECONNECTING TO THE BROWSER…"
                    : (state().note ?? "THE BROWSER STREAM ENDED")}
                </Text>
              </div>
            </Show>
          </div>
        </div>
      </Panel>
    </div>
  );
}
