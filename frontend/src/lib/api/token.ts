/**
 * The session bearer token — the single credential the client sends on every
 * request (including the SSE stream). Held in memory and mirrored to
 * `localStorage` so a reload survives without a re-login; the backend revalidates
 * it on the next call and the session store clears it on `401`/`423`.
 *
 * Kept separate from both the API client and the session store so neither has to
 * import the other (no cycle): the store writes the token, the client reads it.
 */

const TOKEN_KEY = "ody.auth.token";

let inMemory: string | null = null;

function readLS(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return inMemory ?? readLS();
}

export function setToken(token: string): void {
  inMemory = token;
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — in-memory still works for this session */
  }
}

export function clearToken(): void {
  inMemory = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}
