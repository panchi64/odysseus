import type { SessionMode } from "~/lib/modes";
import { SESSION_ACCENT_DEFAULTS, hasSessionSignature } from "./accents";
import { SESSION_KEY, accentOverrides, update } from "./accent-overrides";
import {
  accentValue,
  isAccentOverridden,
  resetAccent,
  setAccent,
} from "./accent-store";
import { normalizeHex } from "./contrast";
import type { ThemeMode } from "./theme-store";

/**
 * The signature accent, read and written per **session mode** — the second axis.
 *
 * Only `--accent` lives here, and that is the design rather than a first
 * increment. The other four accents are a closed set of *meanings*; rebinding
 * "alert" per mode would make red mean one thing in a code thread and another in
 * a research thread, which is the whole failure the closed set prevents. The
 * signature token's job is to say *where you are*, and the mode is exactly that.
 *
 * **Normal has no rule of its own, on purpose.** In the cascade it is the base
 * `--accent`, so every accessor here delegates Normal straight through to
 * `accent-store`. Storing a separate Normal value would create two places that
 * both claim to set the same declaration, and the operator would find the base
 * swatch and the Normal swatch disagreeing with no way to tell which one won.
 */

/** What the signature resolves to for a (theme, session mode) pair — the
 *  operator's override, else the shipped signature, else (for Normal) whatever
 *  the base accent currently resolves to, hand-set or not. */
export function sessionAccentValue(
  mode: ThemeMode,
  sessionMode: SessionMode,
): string {
  if (!hasSessionSignature(sessionMode)) return accentValue(mode, "accent");
  return (
    accentOverrides()[SESSION_KEY]?.[mode]?.[sessionMode] ??
    SESSION_ACCENT_DEFAULTS[mode][sessionMode]
  );
}

/** Whether this pair carries an override. Normal answers for the base token,
 *  which is the thing that moves it. */
export function isSessionAccentOverridden(
  mode: ThemeMode,
  sessionMode: SessionMode,
): boolean {
  if (!hasSessionSignature(sessionMode))
    return isAccentOverridden(mode, "accent");
  return accentOverrides()[SESSION_KEY]?.[mode]?.[sessionMode] !== undefined;
}

/** Set the signature for one session mode in one theme. A value equal to the
 *  shipped signature clears the override, matching `setAccent`. */
export function setSessionAccent(
  mode: ThemeMode,
  sessionMode: SessionMode,
  value: string,
  options?: { persist?: boolean },
): void {
  if (!hasSessionSignature(sessionMode)) {
    setAccent(mode, "accent", value, options);
    return;
  }
  const hex = normalizeHex(value);
  if (!hex) return;
  if (hex === SESSION_ACCENT_DEFAULTS[mode][sessionMode]) {
    resetSessionAccent(mode, sessionMode, options);
    return;
  }
  const current = accentOverrides();
  const session = current[SESSION_KEY] ?? {};
  update(
    {
      ...current,
      [SESSION_KEY]: {
        ...session,
        [mode]: { ...session[mode], [sessionMode]: hex },
      },
    },
    options,
  );
}

/** Clear one session mode's signature, back to the shipped value. */
export function resetSessionAccent(
  mode: ThemeMode,
  sessionMode: SessionMode,
  options?: { persist?: boolean },
): void {
  if (!hasSessionSignature(sessionMode)) {
    resetAccent(mode, "accent", options);
    return;
  }
  const current = accentOverrides();
  const session = { ...current[SESSION_KEY] };
  const perMode = { ...session[mode] };
  delete perMode[sessionMode];
  if (Object.keys(perMode).length > 0) session[mode] = perMode;
  else delete session[mode];
  const next = { ...current };
  if (Object.keys(session).length > 0) next[SESSION_KEY] = session;
  else delete next[SESSION_KEY];
  update(next, options);
}
