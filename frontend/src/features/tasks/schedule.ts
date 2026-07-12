/** Schedule-builder helpers shared by the create/edit form and the task list's
 *  human-readable schedule summary — extracted so the value<->seconds mapping
 *  and cron-shape hint live in exactly one place. */
import type { TaskSchedule } from "./model";

export type IntervalUnit = "seconds" | "minutes" | "hours" | "days";

export const UNIT_SECONDS: Record<IntervalUnit, number> = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
  days: 86400,
};

/** Pick the largest whole unit an interval divides evenly into, for display —
 *  the inverse of the value+unit → seconds mapping the form submits. */
export function secondsToValueUnit(seconds: number): {
  value: string;
  unit: IntervalUnit;
} {
  const units: IntervalUnit[] = ["days", "hours", "minutes", "seconds"];
  for (const unit of units) {
    const size = UNIT_SECONDS[unit];
    if (seconds % size === 0) return { value: String(seconds / size), unit };
  }
  return { value: String(seconds), unit: "seconds" };
}

/** `datetime-local` <-> ISO. `datetime-local` has no timezone, so it's treated
 *  as the operator's local time (matching the native picker's own semantics). */
export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Client-hint-only shape check (five space-separated fields) — the backend is
 *  the validation authority; this is immediate UX feedback. */
export const CRON_PATTERN =
  /^[\d*,\-/]+\s+[\d*,\-/]+\s+[\d*,\-/]+\s+[\d*,\-/]+\s+[\d*,\-/]+$/;

/** One-line, human-readable schedule summary for the task list row. */
export function humanizeSchedule(schedule: TaskSchedule): string {
  switch (schedule.type) {
    case "once":
      return schedule.runAt
        ? new Date(schedule.runAt).toLocaleString()
        : "once";
    case "interval": {
      if (!schedule.everySeconds) return "interval";
      const { value, unit } = secondsToValueUnit(schedule.everySeconds);
      return `every ${value} ${unit}`;
    }
    case "cron":
      return schedule.cron ?? "cron";
    case "webhook":
      return "webhook";
  }
}
