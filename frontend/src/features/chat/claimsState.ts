/**
 * The thread's claim-level reading, fetched once for the panel that shows it.
 *
 * Unlike the source inventory and the command log — both derived from the transcript —
 * this is a separate reading the backend stores sealed and serves on its own route. It
 * is fetched rather than derived because it is genuinely not in the transcript: it is
 * what a *second* model found when it read the answer against the sources the turn
 * retained.
 *
 * **Absent is the ordinary state.** Every non-research thread has none of this, as does
 * every research answer that cited nothing, so an empty read is never an error and never
 * blanks the message-level sources the panel already shows.
 *
 * The same `.latest` discipline `branchState.ts` keeps, for the same reason: a plain read
 * goes `undefined` for the length of a refetch, and the claims would blink out of the
 * panel at exactly the moment a turn finishes and the operator looks up.
 */

import { createResource, createSignal, type Accessor } from "solid-js";
import { extractAttributions, fetchAttributions } from "./data/attributions";
import {
  collectClaims,
  NO_CLAIMS,
  type ClaimInventory,
} from "./viewport/claimItems";

export interface ClaimsStateApi {
  claims: Accessor<ClaimInventory>;
  /** Ask for a reading of the latest answer — the retroactive path, for threads that
   *  finished before the pass existed and for a turn whose live pass degraded. */
  extract: () => void;
  extracting: Accessor<boolean>;
}

/**
 * `revision` is bumped by the caller when a turn settles, which is when the live pass
 * has just run. A research turn's claims therefore arrive on the next read rather than
 * mid-stream — the backend carries no event for them, and the `cited` citations that do
 * stream are the live signal that a reading landed.
 */
export function createClaimsState(
  conversationId: () => string | null,
  revision: () => number,
): ClaimsStateApi {
  const [rows, { mutate, refetch }] = createResource(
    () => {
      const id = conversationId();
      return id === null ? undefined : ([id, revision()] as const);
    },
    ([id]) => fetchAttributions(id),
  );
  const [extracting, setExtracting] = createSignal(false);

  const claims = (): ClaimInventory => {
    const latest = rows.latest;
    return latest ? collectClaims(latest) : NO_CLAIMS;
  };

  const extract = (): void => {
    const id = conversationId();
    if (id === null || extracting()) return;
    setExtracting(true);
    void extractAttributions(id)
      // Written straight into the resource rather than triggering a refetch: the POST
      // already answers with the whole thread's reading, so re-reading it would be a
      // second round trip for bytes just received.
      .then((fresh) => mutate(fresh))
      .catch(() => void refetch())
      .finally(() => setExtracting(false));
  };

  return { claims, extract, extracting };
}
