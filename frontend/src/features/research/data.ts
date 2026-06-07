import {
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import type {
  ResearchReport,
  ResearchRunState,
  ResearchSummary,
  ResearchPhase,
} from "./model";
import { mockReport, mockReportSummaries } from "./mocks";

/* ── Read accessors (the seam) ─────────────────────────────────────────────── */

async function fetchReportSummaries(): Promise<ResearchSummary[]> {
  return mockReportSummaries;
}

async function fetchReport(_id: string): Promise<ResearchReport> {
  return mockReport;
}

export function useReportSummaries(): Resource<ResearchSummary[]> {
  const [data] = createResource(fetchReportSummaries);
  return data;
}

export function useReport(id: () => string): Resource<ResearchReport> {
  const [data] = createResource(id, fetchReport);
  return data;
}

/* ── Mutable summaries store (Phase-1 local state for library actions) ───── */

type SummariesStore = { list: ResearchSummary[] };

let summariesStore: ReturnType<typeof createStore<SummariesStore>> | null =
  null;

/** Returns the shared mutable list used by library action handlers.
 *  Seeded lazily from mockReportSummaries on first call. */
export function useSummariesStore(): ReturnType<
  typeof createStore<SummariesStore>
> {
  if (!summariesStore) {
    summariesStore = createStore<SummariesStore>({
      list: mockReportSummaries.map((s) => ({ ...s })),
    });
  }
  return summariesStore;
}

/* ── Live-run controller ────────────────────────────────────────────────────
   Drives the research phase progress display. Phase 2: replace timers with
   SSE events from the research engine endpoint; RunState shape is unchanged. */

const PHASES: ResearchPhase[] = [
  "PLANNING",
  "SEARCHING",
  "READING",
  "ANALYZING",
  "WRITING",
  "DONE",
];

const PHASE_PROGRESS: Record<ResearchPhase, number> = {
  PLANNING: 8,
  SEARCHING: 28,
  READING: 52,
  ANALYZING: 74,
  WRITING: 92,
  DONE: 100,
};

const PHASE_DURATIONS: Record<ResearchPhase, number> = {
  PLANNING: 900,
  SEARCHING: 2200,
  READING: 3100,
  ANALYZING: 2400,
  WRITING: 2800,
  DONE: 0,
};

export function createResearchRun() {
  const [running, setRunning] = createSignal(false);
  const [state, setState] = createStore<ResearchRunState>({
    phase: "PLANNING",
    round: 1,
    sourcesFound: 0,
    findingsExtracted: 0,
    progress: 0,
    query: "",
    error: null,
  });

  const timers: ReturnType<typeof setTimeout>[] = [];
  const after = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

  function run(query: string) {
    if (!query.trim() || running()) return;
    setRunning(true);
    setState(
      produce((s) => {
        s.query = query.trim();
        s.phase = "PLANNING";
        s.round = 1;
        s.sourcesFound = 0;
        s.findingsExtracted = 0;
        s.progress = 0;
        s.error = null;
      }),
    );

    let elapsed = 0;
    PHASES.forEach((phase, i) => {
      if (phase === "DONE") {
        after(elapsed, () => {
          setState(
            produce((s) => {
              s.phase = "DONE";
              s.progress = 100;
              s.sourcesFound = 31;
              s.findingsExtracted = 47;
              s.round = 4;
            }),
          );
          setRunning(false);
        });
        return;
      }

      after(elapsed, () => {
        setState(
          produce((s) => {
            s.phase = phase;
            s.progress = PHASE_PROGRESS[phase];
          }),
        );
      });

      // Tick up sources / findings during SEARCHING and READING
      if (phase === "SEARCHING") {
        for (let t = 200; t <= PHASE_DURATIONS[phase]; t += 300) {
          after(elapsed + t, () =>
            setState(
              produce((s) => {
                s.sourcesFound = Math.min(s.sourcesFound + 3, 31);
              }),
            ),
          );
        }
      }
      if (phase === "READING") {
        for (let t = 200; t <= PHASE_DURATIONS[phase]; t += 400) {
          after(elapsed + t, () =>
            setState(
              produce((s) => {
                s.findingsExtracted = Math.min(s.findingsExtracted + 4, 47);
              }),
            ),
          );
        }
      }
      // Simulate round advances
      if (phase === "ANALYZING" && i === 3) {
        after(elapsed + PHASE_DURATIONS[phase] * 0.5, () =>
          setState(
            produce((s) => {
              s.round = Math.min(s.round + 2, 4);
            }),
          ),
        );
      }

      elapsed += PHASE_DURATIONS[phase];
    });
  }

  onCleanup(() => timers.forEach(clearTimeout));

  return { running, state, run };
}
