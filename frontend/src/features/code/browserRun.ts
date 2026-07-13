/** Runs HTML/JavaScript snippets inside the app's sandboxed frame vehicle
 *  (`SandboxedFrame`) — a blob: URL document at an opaque origin, never
 *  `eval()`'d in the app's own origin. Shared run-handle shape with
 *  `pythonRun.ts` so `data.ts` can drive either the same way. */

export interface RunCallbacks {
  onLine: (stream: "stdout" | "stderr", line: string) => void;
  onDone: (durationMs: number) => void;
}

export interface RunHandle {
  /** Stop listening/waiting without finalizing a result (user Cancel). */
  cancel(): void;
}

/** A stuck run (e.g. a synchronous infinite loop, or a document that never fires
 *  "load") shouldn't hang the runner forever — finalize as an error past this cap. */
const BROWSER_RUN_TIMEOUT_MS = 15_000;

/** Injected above the user's own source in every HTML/JS run. Overrides
 *  console.log/info/warn/error, window.onerror, and unhandledrejection so the
 *  framed, opaque-origin document (sandboxed without `allow-same-origin`) can
 *  report its output back — postMessage is the only channel it has. */
const BOOTSTRAP_SCRIPT = `<script>
(function () {
  function post(stream, line) {
    parent.postMessage({ source: "ody-run", stream: stream, line: line }, "*");
  }
  function fmt(args) {
    return Array.prototype.map.call(args, function (a) {
      if (typeof a === "string") return a;
      try { return JSON.stringify(a); } catch (e) { return String(a); }
    }).join(" ");
  }
  ["log", "info", "warn", "error"].forEach(function (level) {
    var original = console[level];
    console[level] = function () {
      post(level === "warn" || level === "error" ? "stderr" : "stdout", fmt(arguments));
      if (original) original.apply(console, arguments);
    };
  });
  window.onerror = function (message, source, lineno, colno, error) {
    post("stderr", String((error && error.stack) || message));
    return false;
  };
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    post("stderr", "Unhandled rejection: " + String((reason && reason.stack) || reason));
  });
})();
</script>`;

function buildHtmlDocument(source: string): string {
  return `<!doctype html>
<html>
<head>${BOOTSTRAP_SCRIPT}</head>
<body>
${source}
<script>
window.addEventListener("load", function () {
  parent.postMessage({ source: "ody-run", type: "done" }, "*");
});
<\/script>
</body>
</html>`;
}

function buildJsDocument(source: string): string {
  // Guard the HTML parser against a "</script" substring inside user code (which
  // would otherwise close this wrapper tag before any JS runs). `\/` is a no-op
  // escape inside a JS string literal, so a legitimate value is unaffected.
  const safeSource = source.replace(/<\/script/gi, "<\\/script");
  return `<!doctype html>
<html>
<head>${BOOTSTRAP_SCRIPT}</head>
<body>
<script>
try {
${safeSource}
} catch (e) {
  window.onerror(e && e.message, "", 0, 0, e);
}
parent.postMessage({ source: "ody-run", type: "done" }, "*");
<\/script>
</body>
</html>`;
}

/** Starts one HTML/JS run: mints a blob: document, hands its URL to `onPreview`
 *  (for mounting via `SandboxedFrame`), and folds postMessage output back through
 *  `onLine`/`onDone`. The caller owns revoking the blob URL. */
export function startBrowserRun(
  lang: "html" | "javascript",
  source: string,
  callbacks: RunCallbacks & { onPreview: (src: string) => void },
): RunHandle {
  const startedAt = performance.now();
  const doc =
    lang === "html" ? buildHtmlDocument(source) : buildJsDocument(source);
  const blob = new Blob([doc], { type: "text/html" });
  const src = URL.createObjectURL(blob);
  let finished = false;

  function teardown() {
    window.removeEventListener("message", handleMessage);
    clearTimeout(timeoutId);
  }

  function finish() {
    if (finished) return;
    finished = true;
    teardown();
    callbacks.onDone(Math.round(performance.now() - startedAt));
  }

  function handleMessage(event: MessageEvent) {
    const data = event.data as
      | {
          source?: string;
          type?: string;
          stream?: "stdout" | "stderr";
          line?: string;
        }
      | null
      | undefined;
    if (!data || data.source !== "ody-run") return;
    if (data.type === "done") {
      finish();
      return;
    }
    if (typeof data.line === "string") {
      callbacks.onLine(
        data.stream === "stderr" ? "stderr" : "stdout",
        data.line,
      );
    }
  }

  window.addEventListener("message", handleMessage);
  const timeoutId = setTimeout(finish, BROWSER_RUN_TIMEOUT_MS);
  callbacks.onPreview(src);

  return {
    cancel() {
      if (finished) return;
      finished = true;
      teardown();
    },
  };
}
