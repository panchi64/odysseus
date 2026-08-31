import type { SessionMode } from "~/lib/modes";
import { SESSION_ACCENT_DEFAULTS, hasSessionSignature } from "./accents";
import { createAccentAxis } from "./accent-axis";
import { SESSION_AXIS, accentOverrides, update } from "./accent-overrides";
import {
  accentValue,
  isAccentOverridden,
  resetAccent,
  setAccent,
} from "./accent-store";
import type { ThemeMode } from "./theme-store";

/**
 * The signature accent, read and written per **session mode** — the second axis.
 *
 * Only `--accent` lives here, and that is the design rather than a first increment. The
 * other four accents are a closed set of *meanings*; rebinding "alert" per mode would
 * make red mean one thing in a code thread and another in a research thread, which is
 * the whole failure the closed set prevents. The signature token's job is to say *where
 * you are*, and the mode is exactly that.
 *
 * Mechanically this is `accent-store`'s axis one key level deeper, so it is the same
 * `createAccentAxis` over a longer path — the four accessors, the clear-on-default rule
 * and the prune are not restated.
 *
 * **What is genuinely different is Normal, and it is the only thing left here.** In the
 * cascade Normal *is* the base `--accent`, so every accessor delegates it straight
 * through to `accent-store`. Storing a separate Normal value would create two places
 * that both claim to set the same declaration, and the operator would find the base
 * swatch and the Normal swatch disagreeing with no way to tell which one won.
 */
const axis = createAccentAxis<SessionMode>(
  {
    ...SESSION_AXIS,
    shipped: (theme, mode) => SESSION_ACCENT_DEFAULTS[theme][mode],
  },
  { read: accentOverrides, update },
);

/** What the signature resolves to for a (theme, session mode) pair — the
 *  operator's override, else the shipped signature, else (for Normal) whatever
 *  the base accent currently resolves to, hand-set or not. */
export function sessionAccentValue(
  mode: ThemeMode,
  sessionMode: SessionMode,
): string {
  if (!hasSessionSignature(sessionMode)) return accentValue(mode, "accent");
  return axis.value(mode, sessionMode);
}

/** Whether this pair carries an override. Normal answers for the base token,
 *  which is the thing that moves it. */
export function isSessionAccentOverridden(
  mode: ThemeMode,
  sessionMode: SessionMode,
): boolean {
  if (!hasSessionSignature(sessionMode))
    return isAccentOverridden(mode, "accent");
  return axis.isOverridden(mode, sessionMode);
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
  axis.set(mode, sessionMode, value, options);
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
  axis.reset(mode, sessionMode, options);
}
