/** Global backend-reachability echo — true while the frontend can reach the backend.
 *
 *  A presentation echo only (the backend owns the truth): the REST client flips it
 *  false when a request fails at the transport layer (`fetch` throws — not a deliberate
 *  abort, and not an HTTP error status, which means the server *did* answer) and true on
 *  any received response; the run SSE stream flips it true on a live connect and false
 *  when reconnects are exhausted. Read by the platform-status derivation that tints the
 *  favicon, so a dropped backend shows as "down" from any screen. */
import { createSignal } from "solid-js";

const [backendReachable, setBackendReachable] = createSignal(true);

export { backendReachable, setBackendReachable };
