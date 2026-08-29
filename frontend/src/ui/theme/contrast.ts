/** WCAG contrast maths, for the accent editor's legibility warning.
 *
 *  Pure and dependency-free on purpose — no cascade reads, no DOM. The two mode
 *  backgrounds are literals below rather than `getComputedStyle` lookups, which
 *  is what keeps this module unit-testable (`contrast.test.ts`) and what lets it
 *  answer for the mode the operator is *not* currently looking at.
 *
 *  The design system's floor is in §12: every accent must clear 4.5:1 against
 *  `bg`, re-verified after any hue change. That used to be a promise the tokens
 *  kept because they were fixed. Now that an operator can set them, the floor is
 *  something the interface has to *say* — see `ColorField`. */

import type { ThemeMode } from "./theme-store";

/** The `--bg` of each mode, from tokens.css. Ink is pure black and Paper pure
 *  white by design (§5), so these are stable in a way the accents no longer are. */
export const MODE_BG: Record<ThemeMode, string> = {
  phosphor: "#000000",
  paper: "#ffffff",
};

/** The system's accent contrast floor (§12). */
export const ACCENT_CONTRAST_FLOOR = 4.5;

/** Accepts `#rgb` / `#rrggbb`, with or without the hash, in any case; returns a
 *  normalized `#rrggbb`, or null if it isn't a hex colour at all. Null rather
 *  than a throw: this parses whatever an `<input>` or `localStorage` hands over,
 *  and the caller's job is to ignore junk, not to crash on it. */
export function normalizeHex(input: string): string | null {
  const hex = input.trim().replace(/^#/, "").toLowerCase();
  if (/^[0-9a-f]{3}$/.test(hex))
    return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`;
  if (/^[0-9a-f]{6}$/.test(hex)) return `#${hex}`;
  return null;
}

/** One sRGB channel (0–255) linearized per WCAG 2.x. */
function linearize(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance, 0 (black) to 1 (white). Returns null for a value
 *  that isn't a hex colour. */
export function relativeLuminance(hex: string): number | null {
  const normalized = normalizeHex(hex);
  if (!normalized) return null;
  const r = linearize(parseInt(normalized.slice(1, 3), 16));
  const g = linearize(parseInt(normalized.slice(3, 5), 16));
  const b = linearize(parseInt(normalized.slice(5, 7), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two colours, 1 to 21. Order-independent — the
 *  lighter of the two is always the numerator. Null if either isn't a colour. */
export function contrastRatio(a: string, b: string): number | null {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  if (la === null || lb === null) return null;
  const [lighter, darker] = la >= lb ? [la, lb] : [lb, la];
  return (lighter + 0.05) / (darker + 0.05);
}

/** The ratio of an accent against a mode's background, rounded to one decimal
 *  for display. Null if `hex` isn't a colour. */
export function accentContrast(hex: string, mode: ThemeMode): number | null {
  const ratio = contrastRatio(hex, MODE_BG[mode]);
  return ratio === null ? null : Math.round(ratio * 10) / 10;
}

/** Whether an accent clears §12's 4.5:1 floor against a mode's background.
 *
 *  **Judged on the rounded ratio, deliberately** — the same number the field
 *  displays. A colour at 4.47:1 shows as `4.5:1`, and pairing that with "below
 *  the 4.5:1 floor" reads as a broken interface rather than as a borderline
 *  colour. The verdict and the figure beside it have to agree, and the figure is
 *  the one the operator can see. The cost is a ~0.05 band around the floor that
 *  is called a pass; at that margin the honest answer is "close enough to argue
 *  about", which is not worth contradicting yourself over.
 *
 *  A value that isn't a colour is reported as passing — it is not a contrast
 *  problem, and flagging it as one would put a legibility warning under a field
 *  whose real problem is that it is empty. */
export function meetsAccentFloor(hex: string, mode: ThemeMode): boolean {
  const ratio = accentContrast(hex, mode);
  return ratio === null || ratio >= ACCENT_CONTRAST_FLOOR;
}
