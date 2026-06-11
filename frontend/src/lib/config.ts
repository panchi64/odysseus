/**
 * Runtime configuration for the backend seam.
 *
 * The frontend makes no assumption about who serves it — the backend is a
 * separate origin reached over an absolute base URL. Override at build/run time
 * with `VITE_API_BASE` (see `frontend/.env`); defaults to the local dev backend.
 */
export const API_BASE: string =
  import.meta.env.VITE_API_BASE ?? "http://localhost:7000";

/** Resolve an API path against the backend origin (e.g. for iframe `src`). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
