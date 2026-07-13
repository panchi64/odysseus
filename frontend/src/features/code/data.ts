import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Accessor,
  type Resource,
} from "solid-js";
import type { CodeLanguage, CodeRun, RunStatus } from "./model";
import { starterCode } from "./mocks";
import { loadHistory, saveHistory } from "./historyStore";
import { startBrowserRun, type RunHandle } from "./browserRun";
import { runPython, disposePythonWorker } from "./pythonRun";

async function fetchRuns(): Promise<CodeRun[]> {
  return loadHistory();
}

export function useCodeRuns(): Resource<CodeRun[]> {
  const [data] = createResource(fetchRuns);
  return data;
}

/* ── HTML/JS preview mount ───────────────────────────────────────────────────
   The blob: URL of the current HTML/JS run's sandboxed document, for CodeScreen
   to mount via `SandboxedFrame`. Module-scoped: the screen is a single-instance
   route, and `createCodeRunner`'s own return shape is a fixed, documented
   contract that callers destructure by name — this is the one output of a run
   that isn't console text, so it's exposed as its own small hook instead of
   growing that contract. */
const [previewSrc, setPreviewSrcSignal] = createSignal<string | null>(null);
let currentBlobUrl: string | null = null;

function setPreviewSrc(url: string | null): void {
  if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
  currentBlobUrl = url;
  setPreviewSrcSignal(url);
}

/** The live HTML/JS run's sandboxed document, or null outside a browser run. */
export function useCodePreview(): Accessor<string | null> {
  return previewSrc;
}

/* ── Run controller ──────────────────────────────────────────────────────────
   Drives the editor + output panel. Python runs in a warm Pyodide Web Worker
   (pythonRun.ts); HTML/JS run in the app's sandboxed iframe vehicle
   (browserRun.ts) via a blob: document. Both report back through the same
   { onLine, onDone } shape so this controller doesn't fork per language. */

let runCounter = 0;
const nextRunId = () =>
  `r-${Date.now().toString(36)}-${(++runCounter).toString(36)}`;

export function createCodeRunner(initial: () => CodeRun[] | undefined) {
  const [language, setLanguage] = createSignal<CodeLanguage>("python");
  const [source, setSource] = createSignal(starterCode.python);
  const [running, setRunning] = createSignal(false);
  const [outputLines, setOutputLines] = createSignal<string[]>([]);
  const [lastStatus, setLastStatus] = createSignal<RunStatus | null>(null);
  const [lastDuration, setLastDuration] = createSignal<number | null>(null);
  const [history, setHistory] = createSignal<CodeRun[]>([]);

  let activeCancel: RunHandle["cancel"] | null = null;

  onCleanup(() => {
    activeCancel?.();
    setPreviewSrc(null);
    disposePythonWorker();
  });

  // Seed history once from the (async) resource
  let seeded = false;
  createEffect(() => {
    const data = initial();
    if (!seeded && data) {
      seeded = true;
      setHistory(data.slice());
    }
  });

  function onLanguageChange(value: string) {
    const lang = value as CodeLanguage;
    setLanguage(lang);
    setSource(starterCode[lang]);
    setOutputLines([]);
    setLastStatus(null);
    setPreviewSrc(null);
  }

  function finalize(
    lang: CodeLanguage,
    src: string,
    output: string,
    status: RunStatus,
    durationMs: number,
  ) {
    activeCancel = null;
    setLastStatus(status);
    setLastDuration(durationMs);
    setRunning(false);

    const newRun: CodeRun = {
      id: nextRunId(),
      language: lang,
      source: src,
      output,
      status,
      durationMs,
      ranAt: new Date().toISOString(),
    };
    setHistory((prev) => saveHistory([newRun, ...prev]));
  }

  function runCode() {
    if (running()) return;
    setRunning(true);
    setOutputLines([]);
    setLastStatus(null);
    setLastDuration(null);
    setPreviewSrc(null);

    const lang = language();
    const src = source();
    const lines: string[] = [];
    let sawError = false;

    const onLine = (stream: "stdout" | "stderr", line: string) => {
      lines.push(line);
      setOutputLines((prev) => [...prev, line]);
      if (stream === "stderr") sawError = true;
    };
    const onDone = (durationMs: number) => {
      finalize(
        lang,
        src,
        lines.join("\n"),
        sawError ? "error" : "ok",
        durationMs,
      );
    };

    if (lang === "python") {
      activeCancel = runPython(src, { onLine, onDone }).cancel;
    } else {
      activeCancel = startBrowserRun(lang, src, {
        onPreview: setPreviewSrc,
        onLine,
        onDone,
      }).cancel;
    }
  }

  function cancelRun() {
    if (!running()) return;
    activeCancel?.();
    activeCancel = null;
    setPreviewSrc(null);
    setRunning(false);
  }

  function resetToTemplate() {
    setSource(starterCode[language()]);
    setOutputLines([]);
    setLastStatus(null);
    setLastDuration(null);
    setPreviewSrc(null);
  }

  return {
    language,
    setLanguage: onLanguageChange,
    source,
    setSource,
    running,
    outputLines,
    lastStatus,
    lastDuration,
    history,
    runCode,
    cancelRun,
    resetToTemplate,
  };
}
