/** Deep Research feature data contracts — mirrors the backend wire contract
 *  (`ResearchOut`, `routes/research.py`) camelCase-for-camelCase, the same
 *  convention `features/tasks/model.ts` follows. The seam: screens depend only
 *  on these types; `data.ts` is the only place that talks to the backend. */

export type ResearchStatus =
  | "draft"
  | "running"
  | "done"
  | "error"
  | "cancelled";

/** The frozen plan the operator approved (or accepted as-is) before a run
 *  starts — objective + angles to investigate, plus optional planner notes. */
export interface ResearchPlan {
  objective: string;
  angles: string[];
  notes?: string;
}

/** Run statistics, available once a run has produced them (typically once
 *  `status` is `"done"`, but a partial set may accompany `"error"`/`"cancelled"`). */
export interface ResearchStats {
  durationS: number;
  rounds: number;
  sources: number;
  queries: number;
  model: string;
}

/** One research entry — a draft being clarified/planned, a run in flight, or a
 *  finished (or failed/cancelled) report. Every field beyond the identity trio
 *  is optional because the same shape covers every stage of the lifecycle. */
export interface ResearchOut {
  id: string;
  question: string;
  status: ResearchStatus;
  /** Non-empty when the question was underspecified and the planner wants
   *  answers before committing to a plan. Absent once a plan exists. */
  clarifyingQuestions?: string[];
  /** Present once the planner has produced a preview — its presence is what
   *  drives the START RESEARCH affordance being available (the skip path),
   *  independent of whether `clarifyingQuestions` is also set. */
  plan?: ResearchPlan;
  /** The finished, cited report body (Markdown) — set once `status` is
   *  `"done"`. Citations are inline in the Markdown (links/refs the writer
   *  emitted from the evidence ledger), not a separate structured list — so
   *  rendering it is exactly rendering Markdown, the same as a chat answer.
   *  On `"error"`, the backend writes the clear, operator-facing failure
   *  message into this same field (there is no separate error-message field
   *  on the wire) — so a cold-loaded failed entry still has detail to show. */
  report?: string;
  stats?: ResearchStats;
  /** Set once `status` is `"running"` (or was — a finished entry keeps it for
   *  reference) — the Run this entry's execution rides on. */
  runId?: string;
  /** Set once `POST /research/{id}/continue` has been called — seeds (once)
   *  the follow-up conversation carrying the report as context. */
  conversationId?: string;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
}

/** `GET /research` list item — the same shape, minus the heavy draft/report
 *  fields the library list never renders. */
export type ResearchListItem = Omit<
  ResearchOut,
  "clarifyingQuestions" | "plan" | "report"
>;

/** The five phases the pipeline streams via `step.started.title` (backend
 *  `research/CLAUDE.md`) — lowercase, matching the wire value verbatim. */
export type ResearchPhase =
  | "planning"
  | "searching"
  | "reading"
  | "analyzing"
  | "writing";

/** Live progress folded from a running research entry's run events — the
 *  research-surface counterpart to chat's per-message streaming state. */
export interface ResearchProgressState {
  phase: ResearchPhase | null;
  /** Count of `planning` steps seen so far — each round's own `step.started`
   *  fires it at that round's start, so the count itself is the round number. */
  round: number;
  /** Cumulative, run-wide — folded from `tool.progress`'s `"{n} sources, {n}
   *  findings"` partial (backend `research/CLAUDE.md`), not re-derived locally. */
  sources: number;
  findings: number;
  running: boolean;
  /** The stream's reconnect budget was exhausted — the run may still be alive
   *  server-side; mirrors chat's `detached` state with a reattach affordance. */
  detached: boolean;
  /** The last `run.error`/search-unavailable `limit.notice` message observed
   *  live. Only ever populated by watching an in-progress run — a cold-loaded
   *  failed entry has no live stream to fold, so callers should prefer
   *  `ResearchOut.report` (the backend's error message doubles as the report
   *  field on an error outcome) and fall back to this only while a run is
   *  actively being watched. */
  errorMessage: string | null;
}
