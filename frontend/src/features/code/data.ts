import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import type { CodeLanguage, CodeRun, RunStatus } from "./model";
import { mockRuns, mockOutputs, starterCode } from "./mocks";

async function fetchRuns(): Promise<CodeRun[]> {
  return mockRuns;
}

export function useCodeRuns(): Resource<CodeRun[]> {
  const [data] = createResource(fetchRuns);
  return data;
}

/* ── Run controller ──────────────────────────────────────────────────────────
   Drives the editor + output panel. Phase 2: replace the setInterval streamer
   with a real execution endpoint; the return shape is unchanged. */

let runCounter = 100;
const nextRunId = () => `r-live-${++runCounter}`;

export function createCodeRunner(initial: () => CodeRun[] | undefined) {
  const [language, setLanguage] = createSignal<CodeLanguage>("python");
  const [source, setSource] = createSignal(starterCode["python"]);
  const [running, setRunning] = createSignal(false);
  const [outputLines, setOutputLines] = createSignal<string[]>([]);
  const [lastStatus, setLastStatus] = createSignal<RunStatus | null>(null);
  const [lastDuration, setLastDuration] = createSignal<number | null>(null);
  const [history, setHistory] = createSignal<CodeRun[]>([]);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

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
  }

  function runCode() {
    if (running()) return;
    setRunning(true);
    setOutputLines([]);
    setLastStatus(null);
    setLastDuration(null);

    const lang = language();
    const mock = mockOutputs[lang];
    const lines = mock.output.split("\n").filter(Boolean);
    let i = 0;

    const iv = setInterval(() => {
      if (i < lines.length) {
        setOutputLines((prev) => [...prev, lines[i]]);
        i++;
      } else {
        clearInterval(iv);
        setLastStatus(mock.status);
        setLastDuration(mock.durationMs);
        setRunning(false);

        const newRun: CodeRun = {
          id: nextRunId(),
          language: lang,
          source: source(),
          output: mock.output,
          status: mock.status,
          durationMs: mock.durationMs,
          ranAt: new Date().toISOString(),
        };
        setHistory((prev) => [newRun, ...prev]);
      }
    }, 120);
    timers.push(iv);
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
  };
}
