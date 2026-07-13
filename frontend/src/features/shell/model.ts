/** Operator shell feature data contracts. */

/** Lifecycle of the operator shell UI. The backend owns every transition —
 *  this only names the states the screen renders. */
export type SessionPhase =
  | "prompt"
  | "authenticating"
  | "connecting"
  | "live"
  | "ended"
  | "denied";

/** A short-lived, single-use grant minted by re-authenticating with the
 *  operator password (`POST /shell/host-mode`). Spent by the first WebSocket
 *  auth frame that presents it. */
export interface HostModeGrant {
  token: string;
  expiresInS: number;
}

/** How a live PTY session concluded. */
export interface SessionEnd {
  exitCode: number | null;
  reason: string;
}
