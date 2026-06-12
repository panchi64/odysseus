/**
 * The typed REST client — a thin `fetch` wrapper over the backend.
 *
 * Bearer auth on every request (the token from `./token`); JSON in/out; non-2xx
 * mapped to a typed {@link ApiError}. A `401`/`423` (unauthorized / vault locked)
 * clears the token and fires the registered expiry handler so the session store
 * can route back to login. This is the destination the feature `data.ts` seams
 * swap their mock bodies to.
 */
import { API_BASE } from "~/lib/config";
import { clearToken, getToken } from "./token";

export interface ApiError {
  status: number;
  detail: string;
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    "detail" in value
  );
}

let onExpire: (() => void) | null = null;

/** Register what happens when the backend rejects our token (401/423). */
export function setExpireHandler(fn: () => void): void {
  onExpire = fn;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    /* non-JSON error body — keep the status text */
  }
  return { status: res.status, detail };
}

export interface RequestOptions {
  /** Abort the request when this signal fires (e.g. a per-call timeout). */
  signal?: AbortSignal;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: RequestOptions,
): Promise<T> {
  const headers = authHeaders();
  const init: RequestInit = {
    method,
    headers,
    credentials: "omit",
    signal: opts?.signal,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (res.status === 401 || res.status === 423) {
    clearToken();
    onExpire?.();
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) =>
    request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T = void>(path: string) => request<T>("DELETE", path),
  /** Fetch raw bytes (auth-gated content like artifacts) for a blob URL. */
  async getBlob(path: string): Promise<Blob> {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: authHeaders(),
      credentials: "omit",
    });
    if (res.status === 401 || res.status === 423) {
      clearToken();
      onExpire?.();
    }
    if (!res.ok) throw await toApiError(res);
    return res.blob();
  },
};
