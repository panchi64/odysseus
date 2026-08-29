/** Formatters for consistent, tabular, diegetic-feeling output. */

/** Fixed-decimal number as a tabular string (e.g. 42.7). */
export function num(value: number, decimals = 1): string {
  return value.toFixed(decimals);
}

/** Zero-padded integer (e.g. 0341). */
export function pad(value: number, width = 4): string {
  return Math.trunc(value).toString().padStart(width, "0");
}

/** Percent with no decimals (e.g. 87%).
 *
 *  `digits` adds them back for a figure whose whole point is that it is small: rounding
 *  a 0.6% row to "1%" makes the smallest contributors indistinguishable from each other
 *  and from zero, which in a breakdown is the difference between "these are the rows
 *  that don't matter" and "these rows are broken". */
export function pct(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

/** A duration from milliseconds, at the coarsest unit that still says something
 *  (e.g. `840ms`, `20.5s`, `39m44s`, `2h13m`).
 *
 *  Two units at most, and never a bare decimal above a minute: `39m44s` is read at a
 *  glance where `2384.2s` has to be divided first, and `39.7m` throws away the part a
 *  reader would then try to reconstruct. Below a minute the decimal is the useful
 *  digit — the difference between a 2.4s and a 2.9s first token is real — so seconds
 *  keep one, and only sub-second durations drop to whole milliseconds. */
export function duration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) return `${minutes}m${Math.floor(totalSeconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h${(minutes % 60).toString().padStart(2, "0")}m`;
}

/** A large count abbreviated to three significant figures (e.g. `2.2M`, `450K`, `812`).
 *
 *  For counts that are read as a magnitude rather than a quantity — a thread's token
 *  total is "about two million", and the exact figure belongs in the tooltip.
 *
 *  `precise` keeps the tenth above 10K (`117.4K`, not `117K`). The default drops it
 *  because a lone magnitude is read, not compared — the digit is noise there. It is the
 *  opposite in a *breakdown*, where the figures are read against each other and rounding
 *  to the thousand makes neighbouring rows collide at the exact moment the operator is
 *  ranking them. Same rounding either way, one decision. */
export function compactCount(n: number, precise = false): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000 && !precise) return `${Math.round(n / 1000)}K`;
  if (abs >= 1_000) return `${(n / 1000).toFixed(1)}K`;
  return `${n}`;
}

/** Byte size in IEC units (e.g. 11.2 GB). */
export function bytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Coordinate pair to full precision (diegetic detail). */
export function coord(lat: number, lon: number): string {
  return `${lat.toFixed(7)} ${lon.toFixed(7)}`;
}

/** ISO timestamp -> compact UTC readout (e.g. 2026-06-07 14:32:05Z). */
export function timestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number, w = 2) => n.toString().padStart(w, "0");
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}Z`
  );
}

/** Short date (e.g. 2026-06-07). */
export function date(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
}

/** Coarse relative time (e.g. 3M AGO, 2H AGO, 5D AGO). Uppercase for labels. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const secs = Math.round((now.getTime() - then) / 1000);
  if (secs < 60) return "NOW";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}M AGO`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}H AGO`;
  const days = Math.round(hours / 24);
  return `${days}D AGO`;
}
