import { createSignal } from "solid-js";
import {
  api,
  clearToken,
  getToken,
  isApiError,
  setExpireHandler,
  setToken,
} from "~/lib/api";

/**
 * Session store — the real auth state for the single-operator backend.
 *
 * Odysseus has one operator and a password-derived, memory-only vault key
 * (lock-until-unlocked). There is no multi-user model, no privilege tiers — the
 * only question is whether the workspace is *unlocked* and we hold a valid token.
 *
 * The seam: screens/guards read `useSession()`; the store owns the bearer token
 * (via `~/lib/api/token`) and the backend `/auth/*` calls. A `401`/`423` from any
 * request flips us back to `locked` through the client's expiry handler.
 */

export type SessionStatus = "loading" | "uninitialized" | "locked" | "unlocked";

interface AuthStatus {
  initialized: boolean;
  unlocked: boolean;
  auth_enabled: boolean;
}

interface TokenResponse {
  token: string;
}

const [status, setStatus] = createSignal<SessionStatus>("loading");

/** Map the backend's vault state (plus whether we hold a token) to our status. */
function classify(s: AuthStatus): SessionStatus {
  if (!s.initialized) return "uninitialized";
  if (!s.unlocked) return "locked";
  if (!s.auth_enabled) return "unlocked"; // gate disabled — no token needed
  return getToken() ? "unlocked" : "locked";
}

/** How long one probe may hang before we abandon it. A backend that has bound its
 *  listening socket but hasn't finished starting — exactly what uvicorn's reloader
 *  does, and what the dev server races on a cold boot — *accepts* the connection
 *  and never answers, so a probe with no deadline never settles. That, not a
 *  refused connection, is what used to strand the app on "ESTABLISHING LINK…"
 *  until the operator reloaded the page by hand. */
const PROBE_TIMEOUT_MS = 2000;

/** Backoff between boot re-probes, one entry per retry. Bounded: once it runs out
 *  we settle on `locked`, so a genuinely dead backend lands on the login screen
 *  (which can retry on submit) rather than a splash that never resolves. */
const PROBE_BACKOFF_MS = [250, 500, 1000, 2000];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** One probe attempt. Returns the classified status, or null when the backend
 *  never answered — a transport failure, the only case worth waiting out. An HTTP
 *  error means it *did* answer (it's up, just unhappy), so that settles instead. */
async function probe(): Promise<SessionStatus | null> {
  try {
    return classify(
      await api.get<AuthStatus>("/auth/status", {
        signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
      }),
    );
  } catch (err) {
    return isApiError(err) ? "locked" : null;
  }
}

function apply(next: SessionStatus): SessionStatus {
  if (next !== "unlocked") clearToken(); // a stale token can't unlock us
  setStatus(next);
  return next;
}

/** Probe the backend for the current vault state. */
export async function refresh(): Promise<SessionStatus> {
  // Backend unreachable — present as locked so the login screen can retry.
  return apply((await probe()) ?? "locked");
}

/** The boot probe. The page is routinely up before the backend is, so a single
 *  attempt is a coin flip: retry on a bounded backoff and only then fall back to
 *  `refresh()`'s unreachable handling. The status stays `loading` across the
 *  retries — flashing the login screen at a backend that's merely still starting
 *  would be a worse lie than the splash. */
async function boot(): Promise<void> {
  for (const delay of PROBE_BACKOFF_MS) {
    const next = await probe();
    if (next !== null) {
      apply(next);
      return;
    }
    await sleep(delay);
  }
  await refresh();
}

/** First-run: choose the operator password and unlock. */
export async function setup(password: string): Promise<void> {
  const { token } = await api.post<TokenResponse>("/setup", { password });
  setToken(token);
  setStatus("unlocked");
}

/** Unlock the workspace with the operator password. */
export async function unlock(password: string): Promise<void> {
  const { token } = await api.post<TokenResponse>("/auth/login", { password });
  setToken(token);
  setStatus("unlocked");
}

/** Drop our session token (the vault stays unlocked server-side). */
export async function logout(): Promise<void> {
  try {
    await api.post("/auth/logout");
  } catch {
    /* best effort — clear locally regardless */
  }
  clearToken();
  setStatus("locked");
}

/** Wipe the vault key from the backend's memory and end all sessions. */
export async function lock(): Promise<void> {
  try {
    await api.post("/auth/lock");
  } catch {
    /* best effort — clear locally regardless */
  }
  clearToken();
  setStatus("locked");
}

// A rejected token (expired session / re-locked vault) returns us to locked.
setExpireHandler(() => setStatus("locked"));

// Probe vault state on load (client-only SPA), retrying while the backend comes up.
void boot();

export function useSession() {
  return {
    get status(): SessionStatus {
      return status();
    },
    get isAuthenticated(): boolean {
      return status() === "unlocked";
    },
    refresh,
    setup,
    unlock,
    logout,
    lock,
  };
}
