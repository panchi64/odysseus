import { readLS, writeLS } from "~/lib/storage";
import type { CodeRun } from "./model";

/** All execution is in-browser with no backend — run history is genuinely
 *  client-only state, so persisting it to localStorage (rather than a mock
 *  fixture) is the real seam, not a placeholder for one. */
const HISTORY_KEY = "ody.code.history";
const HISTORY_CAP = 20;

export function loadHistory(): CodeRun[] {
  const raw = readLS(HISTORY_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as CodeRun[]) : [];
  } catch {
    return [];
  }
}

export function saveHistory(history: CodeRun[]): CodeRun[] {
  const capped = history.slice(0, HISTORY_CAP);
  writeLS(HISTORY_KEY, JSON.stringify(capped));
  return capped;
}
