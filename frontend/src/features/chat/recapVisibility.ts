/** When the thread-recap band is worth drawing.
 *
 *  Four conditions, and each one removes a case where the band would be noise rather
 *  than orientation. That is enough rules to be worth testing, and none of them is
 *  about markup — so it lives here rather than in the component, the same split
 *  `compactionLabel.ts` keeps for the divider's own sentence.
 *
 *  Pure: no Solid, no DOM, and the clock is an argument. */

import { parseInstant } from "~/lib/format";
import type { ChatSummary } from "./model";
import { resolveRunState, runStateSpec, type RunState } from "./runState";

/** How long a thread has to have been quiet before the band is worth drawing.
 *
 *  The band answers "what was I doing here", which is only a question once enough time
 *  has passed that the answer has gone. Below this the transcript on screen *is* the
 *  answer, and a paragraph restating what the operator can already see is furniture.
 *  An hour is short enough to catch coming back after lunch and long enough that the
 *  band never appears in the middle of a working session. */
export const COLD_AFTER_MS = 60 * 60 * 1000;

export function showThreadRecap(
  summary: ChatSummary | undefined,
  opts: { streaming: boolean; now: number },
): boolean {
  if (!summary || opts.streaming) return false;
  // Nothing written yet is the ordinary case, not an error: the backend only summarises
  // a thread once it has gone quiet, so every thread is here first and stays here for
  // as long as it is being worked on.
  if (!summary.workSummary) return false;
  // `updatedAt` is the last *message* — the backend keeps it clear of quiet preference
  // writes — so it is a true measure of when work here stopped, not of when the row was
  // last touched for any reason.
  //
  // `parseInstant`, never `new Date`: the wire carries naive UTC with no `Z`, which
  // `Date.parse` reads as *local*. West of Greenwich that puts every thread in the
  // future, the subtraction goes negative, and the band silently never appears — which
  // is exactly how this was found. See the note on `parseInstant`.
  //
  // NaN is a *withhold*, not a fall-through. `parseInstant` answers an unreadable stamp
  // with NaN rather than throwing, and `NaN < COLD_AFTER_MS` is false — so writing this
  // as a bare comparison lets a thread of unknown age past the one gate that exists to
  // establish its age. Asking for the positive fact instead fails closed.
  const quietFor = opts.now - parseInstant(summary.updatedAt);
  if (!(quietFor >= COLD_AFTER_MS)) return false;
  // A live run means this is not a cold thread at all, whatever the clock says: the
  // running turn is the answer, and a recap of the previous one would be reporting the
  // past over the present. `streaming` above covers the thread the operator is watching;
  // this covers one driven from somewhere else.
  return !isLive(summary);
}

/** Whether a run is driving this thread right now, as the shared listing sees it.
 *
 *  Exported so the band's own cells read the same derivation the gate above ran rather
 *  than resolving the pair a second time — two answers to one question is how a band
 *  ends up drawing a state its visibility rule never considered. */
export function runState(summary: ChatSummary): RunState | undefined {
  return resolveRunState(summary.activity, summary.lastOutcome);
}

function isLive(summary: ChatSummary): boolean {
  const state = runState(summary);
  return Boolean(state && runStateSpec(state).live);
}
