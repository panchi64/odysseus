/**
 * Best-effort `localStorage` access. The app is fully client-rendered, but reads
 * and writes can still throw (private mode, storage blocked/full), so every
 * access is guarded and degrades to in-memory-only behaviour for the caller.
 *
 * One home for the guarded access pattern that the token store and feature
 * `data.ts` files both need.
 */

export function readLS(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeLS(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — caller keeps its in-memory value */
  }
}

export function removeLS(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* nothing to clear */
  }
}
