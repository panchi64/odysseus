/**
 * Dedicated Worker running Python via Pyodide off the main thread — a hot loop
 * in the user's script can't freeze the UI, and Stop can `terminate()` this
 * worker outright (the only real way to kill a synchronous busy loop).
 *
 * Assets are self-hosted at `/pyodide/` (see `public/pyodide/`) — fully
 * offline, no CDN URL anywhere. Never runs anything on the Odysseus host.
 *
 * The app's tsconfig uses the DOM lib (no "webworker" lib — the two conflict),
 * so `self` here types as `Window`. Casting to `Worker` gives the actual
 * postMessage/addEventListener shape this global scope has, with no need to
 * touch the shared tsconfig for one file.
 */
import { loadPyodide, type PyodideInterface } from "pyodide";

const ctx = self as unknown as Worker;

interface RunMessage {
  type: "run";
  source: string;
}

let pyodidePromise: Promise<PyodideInterface> | null = null;

function getPyodide(): Promise<PyodideInterface> {
  if (!pyodidePromise) {
    pyodidePromise = loadPyodide({ indexURL: "/pyodide/" }).then((py) => {
      py.setStdout({
        batched: (line) => ctx.postMessage({ type: "stdout", line }),
      });
      py.setStderr({
        batched: (line) => ctx.postMessage({ type: "stderr", line }),
      });
      return py;
    });
  }
  return pyodidePromise;
}

ctx.addEventListener("message", (event) => {
  const data = (event as MessageEvent<RunMessage>).data;
  if (data?.type !== "run") return;
  void (async () => {
    try {
      const py = await getPyodide();
      await py.runPythonAsync(data.source);
      ctx.postMessage({ type: "done" });
    } catch (e) {
      ctx.postMessage({ type: "stderr", line: String(e) });
      ctx.postMessage({ type: "done", error: true });
    }
  })();
});
