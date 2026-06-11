import { createSignal } from "solid-js";
import {
  api,
  clearToken,
  getToken,
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

/** Probe the backend for the current vault state. Called on boot. */
export async function refresh(): Promise<SessionStatus> {
  try {
    const next = classify(await api.get<AuthStatus>("/auth/status"));
    if (next !== "unlocked") clearToken(); // a stale token can't unlock us
    setStatus(next);
    return next;
  } catch {
    // Backend unreachable — present as locked so the login screen can retry.
    setStatus("locked");
    return "locked";
  }
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

// Probe vault state once, on load (client-only SPA).
void refresh();

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
