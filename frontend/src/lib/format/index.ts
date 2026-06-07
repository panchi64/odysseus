/** Formatters for consistent, tabular, diegetic-feeling output. */

/** Fixed-decimal number as a tabular string (e.g. 42.7). */
export function num(value: number, decimals = 1): string {
  return value.toFixed(decimals);
}

/** Zero-padded integer (e.g. 0341). */
export function pad(value: number, width = 4): string {
  return Math.trunc(value).toString().padStart(width, "0");
}

/** Percent with no decimals (e.g. 87%). */
export function pct(value: number): string {
  return `${Math.round(value)}%`;
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
