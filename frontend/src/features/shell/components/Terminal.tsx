import { createEffect, onCleanup, onMount, type JSX } from "solid-js";
import { Terminal as XTerm, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { getToken, handleAuthFailure } from "~/lib/api";
import { useTheme } from "~/ui";
import { buildShellWsUrl, actionForCloseCode } from "../data";
import type { SessionEnd } from "../model";

/* ── PTY terminal ─────────────────────────────────────────────────────────
   Owns xterm + the WebSocket for one live host-mode session. Imperative by
   nature (xterm is a canvas widget, the socket is a raw byte pipe) — this is
   the one place in the feature that isn't resource/store-shaped state. */

const PHOSPHOR_THEME: ITheme = {
  background: "#0A0C0B",
  foreground: "#A8B3AD",
  cursor: "#E6EDE9",
  black: "#0A0C0B",
  brightBlack: "#5A635E",
  red: "#FF3B3B",
  brightRed: "#FF3B3B",
  green: "#5BD47E",
  brightGreen: "#5BD47E",
  yellow: "#FFB020",
  brightYellow: "#FFB020",
  blue: "#3BA9FF",
  brightBlue: "#3BA9FF",
  cyan: "#3BA9FF",
  brightCyan: "#3BA9FF",
  magenta: "#5BD47E",
  brightMagenta: "#5BD47E",
  white: "#A8B3AD",
  brightWhite: "#E6EDE9",
};

const PAPER_THEME: ITheme = {
  background: "#FFFFFF",
  foreground: "#3A3A38",
  cursor: "#0A0A0A",
  black: "#0A0A0A",
  brightBlack: "#9A9A95",
  red: "#1A1A1A",
  brightRed: "#1A1A1A",
  green: "#3A3A38",
  brightGreen: "#3A3A38",
  yellow: "#3A3A38",
  brightYellow: "#3A3A38",
  blue: "#3A3A38",
  brightBlue: "#3A3A38",
  cyan: "#3A3A38",
  brightCyan: "#3A3A38",
  magenta: "#3A3A38",
  brightMagenta: "#3A3A38",
  white: "#3A3A38",
  brightWhite: "#0A0A0A",
};

const MONO_STACK = '"Berkeley Mono", "JetBrains Mono", monospace';

export interface TerminalProps {
  /** The one-time host-mode token minted by the HOST MODE prompt. */
  token: string;
  /** The server confirmed auth and the PTY is live — flips "connecting" to
   *  "live" for the screen. */
  onReady?: () => void;
  onEnded: (end: SessionEnd) => void;
  onAuthFailure: () => void;
  onExpired: () => void;
}

export function Terminal(props: TerminalProps): JSX.Element {
  const theme = useTheme();

  let container: HTMLDivElement | undefined;

  onMount(() => {
    if (!container) return;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const term = new XTerm({
      fontFamily: MONO_STACK,
      fontSize: 13,
      cursorBlink: !reducedMotion,
      theme: theme.resolved === "paper" ? PAPER_THEME : PHOSPHOR_THEME,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    fit.fit();

    // Keep the theme in sync with the app-wide toggle without recreating xterm.
    createEffect(() => {
      term.options.theme =
        theme.resolved === "paper" ? PAPER_THEME : PHOSPHOR_THEME;
    });

    let ready = false;
    let exitCode: number | null = null;
    let stdinDispose: { dispose(): void } | undefined;
    let disposed = false;

    const socket = new WebSocket(buildShellWsUrl());
    socket.binaryType = "arraybuffer";

    function sendResize() {
      if (!ready) return;
      socket.send(
        JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }),
      );
    }

    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          type: "auth",
          bearer: getToken() ?? "",
          host: props.token,
        }),
      );
    };

    socket.onmessage = (ev) => {
      if (disposed) return;
      if (typeof ev.data === "string") {
        let msg: { type: "ready" } | { type: "exit"; code: number };
        try {
          msg = JSON.parse(ev.data) as typeof msg;
        } catch {
          props.onEnded({
            exitCode: null,
            reason: "Lost sync with the host session.",
          });
          return;
        }
        if (msg.type === "ready") {
          ready = true;
          fit.fit();
          stdinDispose = term.onData((data) => {
            socket.send(JSON.stringify({ type: "stdin", data }));
          });
          sendResize();
          props.onReady?.();
        } else if (msg.type === "exit") {
          exitCode = msg.code;
        }
        return;
      }
      term.write(new Uint8Array(ev.data as ArrayBuffer));
    };

    socket.onclose = (ev) => {
      stdinDispose?.dispose();
      const action = actionForCloseCode(ev.code, exitCode);
      if (action.kind === "auth-failure") {
        handleAuthFailure();
        props.onAuthFailure();
      } else if (action.kind === "expired") {
        props.onExpired();
      } else {
        props.onEnded(action.end);
      }
    };

    const ro = new ResizeObserver(() => {
      fit.fit();
      sendResize();
    });
    ro.observe(container);

    onCleanup(() => {
      disposed = true;
      ro.disconnect();
      socket.onmessage = null;
      socket.onopen = null;
      socket.onclose = null;
      stdinDispose?.dispose();
      socket.close();
      term.dispose();
    });
  });

  return (
    <div
      ref={container}
      tabIndex={0}
      class="h-full min-h-0 w-full outline-none focus-visible:ring-2 focus-visible:ring-bright"
    />
  );
}
