/**
 * Runtime configuration for the backend seam.
 *
 * The frontend makes no assumption about who serves it — the backend is a
 * separate origin reached over an absolute base URL. Override at build/run time
 * with `VITE_API_BASE` (see `frontend/.env`); defaults to the local dev backend.
 */
export const API_BASE: string =
  import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

/** Resolve an API path against the backend origin (e.g. for iframe `src`). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/**
 * Resolve an API path against a base as a WebSocket URL, on the matching socket scheme
 * (`https` → `wss`, everything else → `ws`). A relative or scheme-less base (a
 * same-origin deployment) resolves against `here`, so the socket follows the app rather
 * than assuming a host. Pure, and separate from `wsUrl` only so both schemes are
 * testable — `API_BASE` is fixed at module load.
 */
export function toWsUrl(base: string, path: string, here?: string): string {
  const url = new URL(
    base,
    here ?? globalThis.location?.href ?? "http://localhost",
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  // A base may carry a path prefix (an app served under `/api`); its trailing slash
  // would otherwise double up against the leading slash of `path`.
  return `${url.origin}${url.pathname.replace(/\/$/, "")}${path}`;
}

/** Resolve an API path as a WebSocket URL — the same origin `apiUrl` targets. */
export function wsUrl(path: string): string {
  return toWsUrl(API_BASE, path);
}
