import { ACCENT_DEFAULTS, type AccentToken } from "./accents";
import { accentOverrides, update } from "./accent-overrides";
import { normalizeHex } from "./contrast";
import type { ThemeMode } from "./theme-store";

/**
 * The five accent **meanings**, read and written per theme mode.
 *
 * The storage, the guard and the stylesheet are `accent-overrides.ts`; this file
 * is only the vocabulary of the first axis — which token, in which theme, and
 * what it resolves to. `session-accent-store.ts` is its opposite number for the
 * signature-per-session-mode axis, and the two write through the same `update`
 * because there is one sheet and one stored blob.
 *
 * Every accessor here reads the shipped default from `ACCENT_DEFAULTS` rather
 * than from the cascade, and the reason is not performance: by the time any of
 * this runs, the pre-paint script has already applied the overrides on top, so
 * the cascade holds the *current* value — which is exactly not the default the
 * "is this overridden" question is asking about.
 */

/** The value a token currently resolves to for a theme — the override if there
 *  is one, otherwise the shipped default. */
export function accentValue(mode: ThemeMode, token: AccentToken): string {
  return accentOverrides()[mode]?.[token] ?? ACCENT_DEFAULTS[mode][token];
}

/** Whether this token carries an override for this theme. */
export function isAccentOverridden(
  mode: ThemeMode,
  token: AccentToken,
): boolean {
  return accentOverrides()[mode]?.[token] !== undefined;
}

/** Set one token for one theme. A value equal to the shipped default clears the
 *  override rather than storing it, so "I set it back by hand" and "I pressed
 *  reset" leave the same state — otherwise the reset control would linger beside
 *  a token that is no longer overriding anything. */
export function setAccent(
  mode: ThemeMode,
  token: AccentToken,
  value: string,
  options?: { persist?: boolean },
): void {
  const hex = normalizeHex(value);
  if (!hex) return;
  if (hex === ACCENT_DEFAULTS[mode][token]) {
    resetAccent(mode, token, options);
    return;
  }
  const current = accentOverrides();
  update({ ...current, [mode]: { ...current[mode], [token]: hex } }, options);
}

/** Clear one token's override, back to the shipped value. */
export function resetAccent(
  mode: ThemeMode,
  token: AccentToken,
  options?: { persist?: boolean },
): void {
  const current = accentOverrides();
  const perMode = { ...current[mode] };
  delete perMode[token];
  const next = { ...current };
  if (Object.keys(perMode).length > 0) next[mode] = perMode;
  else delete next[mode];
  update(next, options);
}
