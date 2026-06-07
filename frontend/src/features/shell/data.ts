import { createSignal, onCleanup } from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { ShellLine } from "./model";
import { mockInitialLines, mockOutputFor } from "./mocks";

/* ── Shell session controller ────────────────────────────────────────────────
   Owns the scrollback store and the command streamer. Phase 2: replace
   mockOutputFor with a real shell WebSocket/SSE subscription; the return
   shape is unchanged, so ShellScreen doesn't change. */

let lineCounter = mockInitialLines.length;
const nextId = () => `l-live-${++lineCounter}`;

/** Patterns that require a confirm gate before execution. */
export const DANGEROUS_CMD_PATTERNS = [
  /^rm\s/i,
  /^rmdir\s/i,
  /^kill\s+-9\b/i,
  /^truncate\s/i,
  /^dd\s/i,
  /sudo\s/i,
];

export function isDangerousCommand(cmd: string): boolean {
  const trimmed = cmd.trim();
  return DANGEROUS_CMD_PATTERNS.some((re) => re.test(trimmed));
}

export function createShellSession() {
  const [lines, setLines] = createStore<ShellLine[]>([...mockInitialLines]);
  const [input, setInput] = createSignal("");
  const [running, setRunning] = createSignal(false);
  const [cancelled, setCancelled] = createSignal(false);
  const [history, setHistory] = createSignal<string[]>([]);
  const [historyIdx, setHistoryIdx] = createSignal(-1);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  /** Request cancellation of the running command (Phase 2: sends SIGINT). */
  function cancel() {
    if (!running()) return;
    setCancelled(true);
  }

  function run(cmd: string, onScrollBottom?: () => void) {
    if (!cmd || running()) return;

    setRunning(true);
    setCancelled(false);
    setHistory((h) => [cmd, ...h]);
    setHistoryIdx(-1);
    setInput("");

    setLines(
      produce((l) => {
        l.push({
          id: nextId(),
          kind: "command",
          text: cmd,
          at: new Date().toISOString(),
        });
      }),
    );
    onScrollBottom?.();

    const outputLines = mockOutputFor(cmd);
    const hadOutput = outputLines.length > 0;
    let i = 0;

    const interval = setInterval(() => {
      // Handle cancel request
      if (cancelled()) {
        clearInterval(interval);
        setLines(
          produce((l) => {
            l.push({
              id: nextId(),
              kind: "stderr",
              text: "^C",
              at: new Date().toISOString(),
            });
          }),
        );
        onScrollBottom?.();
        setRunning(false);
        setCancelled(false);
        return;
      }

      const line = outputLines[i];
      const isErr =
        line?.toLowerCase().includes("error") ||
        line?.toLowerCase().includes("stderr");
      setLines(
        produce((l) => {
          l.push({
            id: nextId(),
            kind: isErr ? "stderr" : "stdout",
            text: line ?? "",
            at: new Date().toISOString(),
          });
        }),
      );
      onScrollBottom?.();
      i++;
      if (i >= outputLines.length) {
        clearInterval(interval);
        // When the command produced no output, append a dim success marker so
        // the user knows the command ran and completed (e.g. mkdir, touch, mv).
        if (!hadOutput) {
          setLines(
            produce((l) => {
              l.push({
                id: nextId(),
                kind: "stdout",
                text: "  [ok]",
                at: new Date().toISOString(),
              });
            }),
          );
          onScrollBottom?.();
        }
        setRunning(false);
      }
    }, 120);
    timers.push(interval);
  }

  return {
    lines,
    input,
    setInput,
    running,
    cancel,
    history,
    historyIdx,
    setHistoryIdx,
    run,
  };
}
