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

export function createShellSession() {
  const [lines, setLines] = createStore<ShellLine[]>([...mockInitialLines]);
  const [input, setInput] = createSignal("");
  const [running, setRunning] = createSignal(false);
  const [history, setHistory] = createSignal<string[]>([]);
  const [historyIdx, setHistoryIdx] = createSignal(-1);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  function run(cmd: string, onScrollBottom?: () => void) {
    if (!cmd || running()) return;

    setRunning(true);
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
    let i = 0;
    const interval = setInterval(() => {
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
    history,
    historyIdx,
    setHistoryIdx,
    run,
  };
}
