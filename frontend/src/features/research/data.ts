import { createResource, createSignal, type Resource } from "solid-js";
import { createStore } from "solid-js/store";
import { api, isApiError } from "~/lib/api";
import { StreamDetachedError, streamRun, type RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import type {
  ResearchListItem,
  ResearchOut,
  ResearchPhase,
  ResearchProgressState,
} from "./model";

/* ── Draft flow (intake → clarify/refine → start) — plain REST, no Run involved
   until `start` mints one (design: the pre-run stage is lightweight REST/utility
   calls, not a parked Run). Each call returns the revised `ResearchOut` directly,
   so the entry screen updates its local view from the response — no refetch. ── */

export async function intakeResearch(question: string): Promise<ResearchOut> {
  const out = await api.post<ResearchOut>("/research/intake", { question });
  refreshResearchList();
  return out;
}

export interface RefineInput {
  answers?: string[];
  feedback?: string;
}

export async function refineResearch(
  id: string,
  input: RefineInput,
): Promise<ResearchOut> {
  return api.post<ResearchOut>(`/research/${id}/refine`, input);
}

export async function startResearch(id: string): Promise<ResearchOut> {
  const out = await api.post<ResearchOut>(`/research/${id}/start`, {});
  refreshResearchList();
  return out;
}

export async function continueResearch(
  id: string,
): Promise<{ conversationId: string }> {
  return api.post<{ conversationId: string }>(`/research/${id}/continue`, {});
}

export async function deleteResearch(id: string): Promise<void> {
  await api.del(`/research/${id}`);
  refreshResearchList();
}

/* ── Library list ──────────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchResearchList(): Promise<ResearchListItem[]> {
  const { items } = await api.get<{ items: ResearchListItem[] }>("/research");
  return items;
}

export function useResearchList(): Resource<ResearchListItem[]> {
  const [data] = createResource(listTick, fetchResearchList);
  return data;
}

export function refreshResearchList(): void {
  setListTick((n) => n + 1);
}

/* ── Single entry (the draft/progress/report screen) ──────────────────────── */

const [entryTick, setEntryTick] = createSignal(0);

export function useResearchEntry(id: () => string): Resource<ResearchOut> {
  const [data] = createResource(
    () => ({ id: id(), tick: entryTick() }),
    (src) => api.get<ResearchOut>(`/research/${src.id}`),
  );
  return data;
}

/** Refetch the current entry — used once a run reaches a terminal event, since
 *  the finished report/stats/final status live on `ResearchOut`, not the event
 *  stream (see `createResearchProgress`'s `onTerminal`). */
export function refreshResearchEntry(): void {
  setEntryTick((n) => n + 1);
}

/* ── Live progress controller ─────────────────────────────────────────────────
   Folds a running entry's run events into a small store — the research-surface
   counterpart to chat's `foldEvent`/`driveRun`, scoped to exactly what the
   pipeline documents it streams (backend `research/CLAUDE.md`): step.started's
   `title` is the phase, a `planning` step's count is the round number,
   `tool.progress`'s partial is the cumulative sources/findings, and a search-
   unavailable `limit.notice` (immediately followed by `run.error`) is the one
   robustness case with an operator-facing message. Reattach mirrors chat's cold-
   reload path: a `"running"` entry loaded fresh resumes from seq 0, replaying
   the whole buffer to rebuild phase/round/counts rather than trusting a snapshot. ── */

const ROUND_COUNTS_RE = /(\d+)\s+sources,\s+(\d+)\s+findings/;

export interface ResearchProgressController {
  state: ResearchProgressState;
  /** Start (or resume, via `fromSeq`) following a run's events. */
  start: (runId: string, fromSeq?: number) => Promise<void>;
  /** Re-attach after a `detached` transport gave up — resumes from the last
   *  folded seq, same as chat's reattach affordance. */
  reattach: () => void;
  /** `POST /runs/{id}/cancel` — cancellation itself is backend-owned; this only
   *  relays the request. Progress reflects the eventual `run.ended`. */
  cancel: () => Promise<void>;
  /** Abort the local stream reader (screen teardown) without cancelling the run. */
  stop: () => void;
  /** Called once the run reaches a terminal event — the entry's `report`/`stats`/
   *  final `status` live on `ResearchOut`, not the event stream, so the caller
   *  refetches the entry when this fires. */
  onTerminal: (fn: () => void) => void;
}

export function createResearchProgress(): ResearchProgressController {
  const [state, setState] = createStore<ResearchProgressState>({
    phase: null,
    round: 0,
    sources: 0,
    findings: 0,
    running: false,
    detached: false,
    errorMessage: null,
  });

  let controller: AbortController | null = null;
  let maxFoldedSeq = 0;
  let currentRunId: string | null = null;
  let terminalCb: (() => void) | null = null;

  function foldEvent(ev: RunEvent): void {
    if (ev.seq <= maxFoldedSeq) return;
    maxFoldedSeq = ev.seq;
    switch (ev.type) {
      case "step.started": {
        const phase = ev.title as ResearchPhase | null;
        setState("phase", phase);
        if (phase === "planning") setState("round", (r) => r + 1);
        break;
      }
      case "tool.progress": {
        const m = ROUND_COUNTS_RE.exec(ev.partial ?? "");
        if (m) {
          setState("sources", Number(m[1]));
          setState("findings", Number(m[2]));
        }
        break;
      }
      case "limit.notice":
        // The frozen union's `limit` field is a plain string on the backend
        // (`runs/events.py`); "search" (DR-4.1's two-empty-rounds abort) is a
        // valid value the closed frontend literal doesn't (yet) enumerate —
        // cast rather than widen that shared mirror from here.
        if ((ev.limit as string) === "search")
          setState("errorMessage", ev.message);
        break;
      case "run.error":
        setState("errorMessage", ev.message);
        break;
      default:
        break;
    }
  }

  async function start(runId: string, fromSeq = 0): Promise<void> {
    controller?.abort();
    const resuming = runId === currentRunId;
    currentRunId = runId;
    maxFoldedSeq = fromSeq;
    setState({
      running: true,
      detached: false,
      errorMessage: null,
      ...(resuming ? {} : { phase: null, round: 0, sources: 0, findings: 0 }),
    });
    controller = new AbortController();
    try {
      await streamRun(runId, {
        signal: controller.signal,
        fromSeq,
        onEvent: foldEvent,
      });
      setState("running", false);
      terminalCb?.();
    } catch (err) {
      if (err instanceof StreamDetachedError) {
        setState({ running: false, detached: true });
      } else {
        setState("running", false);
      }
    }
  }

  function reattach(): void {
    if (!currentRunId) return;
    void start(currentRunId, maxFoldedSeq);
  }

  async function cancel(): Promise<void> {
    if (!currentRunId) return;
    try {
      await api.post(`/runs/${currentRunId}/cancel`, {});
    } catch (err) {
      toast.error(isApiError(err) ? err.detail : "Unable to cancel the run.");
    }
  }

  function stop(): void {
    controller?.abort();
  }

  return {
    state,
    start,
    reattach,
    cancel,
    stop,
    onTerminal: (fn) => {
      terminalCb = fn;
    },
  };
}
