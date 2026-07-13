import { api } from "~/lib/api";
import { API_BASE } from "~/lib/config";
import type { HostModeGrant, SessionEnd } from "./model";

/* ── Operator shell data seam ────────────────────────────────────────────────
   Host-mode re-auth is a plain REST call; the live session itself rides a
   WebSocket carrying raw PTY bytes, which is imperative and owned by the
   Terminal component (xterm + the socket are not resource-shaped state). */

/** Re-authenticate with the operator password to mint a one-time host-mode
 *  token. The backend decides validity/lockout/rate-limiting; this only
 *  relays the request and reshapes the response to `model.ts`. */
export async function requestHostMode(
  password: string,
): Promise<HostModeGrant> {
  const r = await api.post<{ token: string; expires_in_s: number }>(
    "/shell/host-mode",
    { password },
  );
  return { token: r.token, expiresInS: r.expires_in_s };
}

/** The operator-shell WebSocket endpoint, derived from the same API origin
 *  the REST client uses (scheme swapped http→ws / https→wss). */
export function buildShellWsUrl(): string {
  return `${API_BASE.replace(/^http/, "ws")}/shell/ws`;
}

/** What the UI should do next for a given WebSocket close code, per the
 *  operator-shell wire contract. Pure mapping — no side effects; the caller
 *  (Terminal) performs the actual auth-failure/reconnect/end handling. */
export type CloseAction =
  | { kind: "auth-failure" }
  | { kind: "expired" }
  | { kind: "ended"; end: SessionEnd };

export function actionForCloseCode(
  code: number,
  exitCode: number | null,
): CloseAction {
  switch (code) {
    case 4401:
    case 4423:
      return { kind: "auth-failure" };
    case 4403:
    case 4408:
      return { kind: "expired" };
    case 4409:
      return {
        kind: "ended",
        end: { exitCode: null, reason: "Host busy — session limit reached." },
      };
    default:
      return {
        kind: "ended",
        end: {
          exitCode,
          reason:
            code === 1000 ? "Session ended." : `Connection closed (${code}).`,
        },
      };
  }
}
