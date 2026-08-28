import type { RunCallbacks, RunHandle } from "./browserRun";

/** Runs Python snippets in a warm, lazily-created Pyodide Web Worker. Kept
 *  module-scoped (not per-runner-instance) so a rerun after the first is
 *  instant instead of reloading the ~10MB runtime — mirrors the singleton
 *  resource pattern used for the theme store / chat session list. */

/** A stuck run (a hot loop with no natural end) is finalized as an error past
 *  this cap, and the worker that was running it is terminated. */
const PY_RUN_TIMEOUT_MS = 30_000;

interface WorkerOutMessage {
  type: "stdout" | "stderr" | "done";
  line?: string;
  error?: boolean;
}

let worker: Worker | null = null;

function ensureWorker(): Worker {
  if (!worker) {
    worker = new Worker(new URL("./pyodide.worker.ts", import.meta.url), {
      type: "module",
    });
  }
  return worker;
}

/** Terminates the worker (if any) so the next run lazily recreates it. Call on
 *  a hung/timed-out run, on Cancel (the only way to kill a hot loop), and on
 *  route leave. */
export function disposePythonWorker(): void {
  worker?.terminate();
  worker = null;
}

export function runPython(source: string, callbacks: RunCallbacks): RunHandle {
  const startedAt = performance.now();
  const w = ensureWorker();
  let finished = false;

  function teardown() {
    w.removeEventListener("message", handleMessage);
    clearTimeout(timeoutId);
  }

  function finish(timedOut: boolean) {
    if (finished) return;
    finished = true;
    teardown();
    if (timedOut) {
      callbacks.onLine(
        "stderr",
        `Execution timed out after ${PY_RUN_TIMEOUT_MS / 1000}s — worker terminated.`,
      );
    }
    callbacks.onDone(Math.round(performance.now() - startedAt));
  }

  function handleMessage(event: MessageEvent<WorkerOutMessage>) {
    const data = event.data;
    if (data.type === "stdout" || data.type === "stderr") {
      if (typeof data.line === "string") callbacks.onLine(data.type, data.line);
      return;
    }
    if (data.type === "done") finish(false);
  }

  const timeoutId = setTimeout(() => {
    disposePythonWorker(); // only a hard kill stops a synchronous hot loop
    finish(true);
  }, PY_RUN_TIMEOUT_MS);

  w.addEventListener("message", handleMessage);
  w.postMessage({ type: "run", source });

  return {
    cancel() {
      if (finished) return;
      finished = true;
      teardown();
      disposePythonWorker();
    },
  };
}
