import { createSignal } from "solid-js";
import { isServer } from "solid-js/web";
import {
  ACCENT_DEFAULTS,
  ACCENT_TOKEN_NAMES,
  isAccentToken,
  type AccentToken,
} from "./accents";
import { normalizeHex } from "./contrast";
import type { ThemeMode } from "./theme-store";

/**
 * The operator's accent overrides. Sits beside `theme-store` because it is the
 * same kind of state — UI-owned, device-local, and applied to the cascade rather
 * than held by the backend.
 *
 * **The overrides reach the cascade through one `<style>` element, not through
 * inline styles on `<html>`.** That is the whole design, and it follows from one
 * fact: the overrides are *per mode*, and the mode changes at runtime — a
 * `"system"` preference flips with the OS while the page is open. An inline
 * style can only hold one mode's values, so every flip would have to rewrite it,
 * and any moment the two disagreed would paint the wrong palette. A stylesheet
 * carrying both rules lets the existing `[data-theme]` switch do the selecting,
 * which means `applyTheme` needs no knowledge of accents at all.
 *
 * `html[data-theme="…"]` is specificity (0,1,1), which beats tokens.css's
 * `:root` and `[data-theme="paper"]` (0,1,0) regardless of where the sheet lands
 * in source order — so this does not depend on load timing.
 *
 * Because theme.css maps the tokens with Tailwind's `@theme inline`, overriding
 * the raw `--accent*` custom property is enough to move everything downstream:
 * every `text-*`/`bg-*` utility, `--shadow-accent`/`--shadow-alert` (which are
 * `color-mix`es of `--accent`), the reasoning wall's tint, and every `LedEdge`
 * tone, whose `--led` resolves from these same properties. Nothing else needs
 * to know this feature exists.
 */

export const ACCENT_STORAGE_KEY = "odysseus:accents";

/** The id the pre-paint script in `entry-server.tsx` gives its element. The
 *  store *adopts* that element rather than appending a second one — two sheets
 *  both setting `--accent` would leave the winner up to source order. */
const STYLE_ELEMENT_ID = "ody-accent-overrides";

const MODES: readonly ThemeMode[] = ["phosphor", "paper"];

/** Sparse by design: only what the operator actually changed is stored, so a
 *  token left alone keeps following the shipped palette if that palette is ever
 *  retuned. */
export type AccentOverrides = Partial<
  Record<ThemeMode, Partial<Record<AccentToken, string>>>
>;

/** Drop anything that isn't a known token holding a real hex colour. This runs
 *  over `localStorage`, which is user-writable and is concatenated into a
 *  stylesheet below — so the guard is load-bearing, not tidiness. */
function sanitize(raw: unknown): AccentOverrides {
  if (!raw || typeof raw !== "object") return {};
  const clean: AccentOverrides = {};
  for (const mode of MODES) {
    const entry = (raw as Record<string, unknown>)[mode];
    if (!entry || typeof entry !== "object") continue;
    const perMode: Partial<Record<AccentToken, string>> = {};
    for (const [key, value] of Object.entries(entry as object)) {
      if (!isAccentToken(key) || typeof value !== "string") continue;
      const hex = normalizeHex(value);
      if (hex) perMode[key] = hex;
    }
    if (Object.keys(perMode).length > 0) clean[mode] = perMode;
  }
  return clean;
}

function readStored(): AccentOverrides {
  if (isServer || typeof localStorage === "undefined") return {};
  try {
    return sanitize(
      JSON.parse(localStorage.getItem(ACCENT_STORAGE_KEY) ?? "{}"),
    );
  } catch {
    return {};
  }
}

const [overrides, setOverridesSignal] =
  createSignal<AccentOverrides>(readStored());

/** The CSS the override sheet holds. Exported so a test can assert its shape
 *  without a DOM — it is the one piece of this module that is pure. */
export function serializeOverrides(value: AccentOverrides): string {
  let css = "";
  for (const mode of MODES) {
    const perMode = value[mode];
    if (!perMode) continue;
    let body = "";
    // Iterate the known token list rather than the object's own keys, so the
    // emitted order is stable and nothing unvetted can reach the sheet.
    for (const token of ACCENT_TOKEN_NAMES) {
      const hex = perMode[token] ? normalizeHex(perMode[token]!) : null;
      if (hex) body += `--${token}:${hex};`;
    }
    if (body) css += `html[data-theme="${mode}"]{${body}}`;
  }
  return css;
}

function applyOverrides(value: AccentOverrides): void {
  if (isServer || typeof document === "undefined") return;
  const css = serializeOverrides(value);
  let el = document.getElementById(STYLE_ELEMENT_ID);
  if (!el) {
    // Nothing to say and nothing already saying it — don't add an empty sheet.
    if (!css) return;
    el = document.createElement("style");
    el.id = STYLE_ELEMENT_ID;
    document.head.appendChild(el);
  }
  el.textContent = css;
}

function persist(value: AccentOverrides): void {
  if (isServer || typeof localStorage === "undefined") return;
  try {
    if (Object.keys(value).length > 0)
      localStorage.setItem(ACCENT_STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(ACCENT_STORAGE_KEY);
  } catch {
    /* storage unavailable — the palette is best-effort, like the draft cache */
  }
}

/** Repaint now; write to storage only if asked. The picker drags through
 *  hundreds of `input` events, and every one of them should be visible while
 *  none of them should hit `localStorage` — the caller commits on `change`. */
function update(next: AccentOverrides, options?: { persist?: boolean }): void {
  setOverridesSignal(next);
  applyOverrides(next);
  if (options?.persist !== false) persist(next);
}

/** The value a token currently resolves to for a mode — the override if there is
 *  one, otherwise the shipped default. */
export function accentValue(mode: ThemeMode, token: AccentToken): string {
  return overrides()[mode]?.[token] ?? ACCENT_DEFAULTS[mode][token];
}

/** Whether this token carries an override for this mode. */
export function isAccentOverridden(
  mode: ThemeMode,
  token: AccentToken,
): boolean {
  return overrides()[mode]?.[token] !== undefined;
}

/** Whether anything at all is overridden, in any mode. */
export function hasAccentOverrides(): boolean {
  return MODES.some((mode) => Object.keys(overrides()[mode] ?? {}).length > 0);
}

/** Set one token for one mode. A value equal to the shipped default clears the
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
  const current = overrides();
  update({ ...current, [mode]: { ...current[mode], [token]: hex } }, options);
}

/** Clear one token's override, back to the shipped value. */
export function resetAccent(
  mode: ThemeMode,
  token: AccentToken,
  options?: { persist?: boolean },
): void {
  const current = overrides();
  const perMode = { ...current[mode] };
  delete perMode[token];
  const next = { ...current };
  if (Object.keys(perMode).length > 0) next[mode] = perMode;
  else delete next[mode];
  update(next, options);
}

/** Clear every override in every mode. Returns what was cleared, so the caller
 *  can offer UNDO without holding its own copy. */
export function resetAllAccents(): AccentOverrides {
  const previous = overrides();
  update({});
  return previous;
}

/** Put a whole override set back — the other half of UNDO. */
export function restoreAccents(value: AccentOverrides): void {
  update(sanitize(value));
}

/** Reactive accessor, for anything that needs to re-render on a palette change. */
export { overrides as accentOverrides };
