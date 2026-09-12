/**
 * The thread's sub-agents, kept current for as long as any of them is working.
 *
 * Created once by the room and handed to whoever wants it, the same as the branch beside
 * it: the header does not want it today, but the panel and the surface registry both do,
 * and two `createResource`s over one endpoint are two answers that disagree while either
 * is in flight.
 *
 * **It polls, and that is the design rather than a shortcut.** A sub-agent outlives every
 * stream there is to hang it on — its own ends when it does, and the launching turn's ends
 * long before that — so "tell me when this changes" would need a third stream fanning the
 * others in, held open per conversation for as long as anyone might look. Re-asking a
 * local endpoint for a short list is the same information without that machine, and it is
 * also the only version that is right after a restart.
 *
 * **Only while something is live.** The interval starts when a sub-agent is working and
 * stops when the last one finishes, so a thread whose sub-agents are all done — which is
 * most threads, most of the time — costs exactly one request when it is opened. A card
 * that has finished cannot change again.
 */

import {
  createEffect,
  createResource,
  onCleanup,
  type Resource,
} from "solid-js";
import { fetchSubagents, isLive, type Subagent } from "./data";

/** How often to re-ask while something is working. Fast enough that a context ring and a
 *  status read as live, slow enough to be invisible: the answer is a short list from a
 *  local process, and nothing here is worth a stream. */
const POLL_MS = 3000;

export interface SubagentsApi {
  subagents: Resource<Subagent[]>;
  /** What consumers read: the last answer, held across a re-fetch. */
  latest: () => Subagent[];
  refetch: () => void;
}

/**
 * `revision` is bumped by the caller when a turn settles — the moment a launch is most
 * likely to have just happened, so the first card appears without waiting for a tick.
 *
 * **`latest`, not the resource's own value.** A plain read goes `undefined` for the length
 * of every re-fetch, which on a three-second poll means the panel emptying and refilling
 * continuously while the operator is reading it.
 */
export function createSubagentsState(
  conversationId: () => string | null,
  revision: () => number,
): SubagentsApi {
  const [subagents, { refetch }] = createResource(
    () => {
      const id = conversationId();
      return id === null ? undefined : ([id, revision()] as const);
    },
    ([id]) => fetchSubagents(id),
  );
  const latest = (): Subagent[] => subagents.latest ?? [];

  createEffect(() => {
    // Reading `latest()` here is what makes this self-sustaining: each poll's result
    // re-runs the effect, which re-arms the timer only while the answer still has
    // something live in it.
    if (!latest().some(isLive)) return;
    const timer = setTimeout(() => void refetch(), POLL_MS);
    onCleanup(() => clearTimeout(timer));
  });

  return { subagents, latest, refetch: () => void refetch() };
}
