import { createSignal } from "solid-js";
import { SESSION_MODE_IDS, isSessionMode, type SessionMode } from "~/lib/modes";
import { isServer } from "solid-js/web";
import {
  ACCENT_TOKEN_NAMES,
  hasSessionSignature,
  isAccentToken,
} from "./accents";
import type { AccentToken } from "./accents";
import { normalizeHex } from "./contrast";
import type { ThemeMode } from "./theme-store";

/**
 * The operator's accent overrides: the stored shape, the guard over it, and the
 * one stylesheet it becomes. Sits beside `theme-store` because it is the same
 * kind of state — UI-owned, device-local, and applied to the cascade rather than
 * held by the backend.
 *
 * **The overrides reach the cascade through one `<style>` element, not through
 * inline styles on `<html>`.** That is the whole design, and it follows from one
 * fact: the overrides are *per theme mode*, and the theme changes at runtime — a
 * `"system"` preference flips with the OS while the page is open. An inline
 * style can only hold one theme's values, so every flip would have to rewrite
 * it, and any moment the two disagreed would paint the wrong palette. A
 * stylesheet carrying both rules lets the existing `[data-theme]` switch do the
 * selecting, which means `applyTheme` needs no knowledge of accents at all.
 *
 * The same trick carries the second axis. `data-mode` on the root says which
 * kind of thread is open (`session-mode.ts`), and the sheet emits
 * `html[data-theme=…][data-mode=…]` rules for the signature token — so switching
 * threads repaints the signature with no code running at all.
 *
 * `html[data-theme="…"]` is specificity (0,1,1) and the session rule (0,2,1),
 * which beat tokens.css's `:root` / `[data-theme="paper"]` (0,1,0) and its
 * session block (0,2,0) regardless of where the sheet lands in source order — so
 * none of this depends on load timing.
 *
 * Because theme.css maps the tokens with Tailwind's `@theme inline`, overriding
 * the raw `--accent*` custom property is enough to move everything downstream:
 * every `text-*`/`bg-*` utility, `--shadow-accent`/`--shadow-alert` (which are
 * `color-mix`es of `--accent`), the reasoning wall's tint, and every `LedEdge`
 * tone, whose `--led` resolves from these same properties. Nothing else needs
 * to know this feature exists.
 *
 * The per-axis accessors live next door — `accent-store.ts` for the five accent
 * meanings, `session-accent-store.ts` for the signature per session mode. Both
 * write through `update` here, because there is one sheet and one stored blob:
 * two modules each owning half of a single `<style>` element would leave the
 * winner up to whichever wrote last.
 */

export const ACCENT_STORAGE_KEY = "odysseus:accents";

/** The id the pre-paint script in `entry-server.tsx` gives its element. The
 *  store *adopts* that element rather than appending a second one — two sheets
 *  both setting `--accent` would leave the winner up to source order. */
const STYLE_ELEMENT_ID = "ody-accent-overrides";

/** The theme modes, spelled out so the emitted sheet has a stable order and
 *  nothing unvetted can reach it. Named `THEMES` rather than `MODES` now that a
 *  second axis also calls itself a mode. */
export const THEMES: readonly ThemeMode[] = ["phosphor", "paper"];

/** The reserved key the session-mode signatures live under. It cannot collide
 *  with a `ThemeMode`, which is what lets the shape grow without a stored-format
 *  migration — a blob written before this axis existed still loads, and its five
 *  tokens still apply. */
export const SESSION_KEY = "sessionAccent";

/** The signature accent per (theme, session mode). Sparse like everything else
 *  here, and confined to `accent` on purpose — see `SESSION_ACCENT_DEFAULTS`.
 *  Normal is absent by construction: it *is* the base token, so overriding it
 *  there is what changes it. */
export type SessionAccentOverrides = Partial<
  Record<ThemeMode, Partial<Record<SessionMode, string>>>
>;

/** Sparse by design: only what the operator actually changed is stored, so a
 *  token left alone keeps following the shipped palette if that palette is ever
 *  retuned.
 *
 *  Two axes, side by side rather than nested: the five accent *meanings* per
 *  theme, and — under a reserved key — the signature accent per session mode.
 *  Growing the existing per-theme record instead would have meant a key that is
 *  sometimes a token and sometimes a mode, which `isAccentToken` could no longer
 *  guard on its own. */
export type AccentOverrides = Partial<
  Record<ThemeMode, Partial<Record<AccentToken, string>>>
> & { [SESSION_KEY]?: SessionAccentOverrides };

/** Drop anything that isn't a known token holding a real hex colour. This runs
 *  over `localStorage`, which is user-writable and is concatenated into a
 *  stylesheet below — so the guard is load-bearing, not tidiness. */
export function sanitize(raw: unknown): AccentOverrides {
  if (!raw || typeof raw !== "object") return {};
  const clean: AccentOverrides = {};
  for (const theme of THEMES) {
    const entry = (raw as Record<string, unknown>)[theme];
    if (!entry || typeof entry !== "object") continue;
    const perTheme: Partial<Record<AccentToken, string>> = {};
    for (const [key, value] of Object.entries(entry as object)) {
      if (!isAccentToken(key) || typeof value !== "string") continue;
      const hex = normalizeHex(value);
      if (hex) perTheme[key] = hex;
    }
    if (Object.keys(perTheme).length > 0) clean[theme] = perTheme;
  }
  const session = sanitizeSession(
    (raw as Record<string, unknown>)[SESSION_KEY],
  );
  if (session) clean[SESSION_KEY] = session;
  return clean;
}

/** The same guard for the second axis: a known theme, a known session mode, a
 *  real hex — and never Normal, whose value is the base token and has no rule of
 *  its own to write. */
function sanitizeSession(raw: unknown): SessionAccentOverrides | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const clean: SessionAccentOverrides = {};
  for (const theme of THEMES) {
    const entry = (raw as Record<string, unknown>)[theme];
    if (!entry || typeof entry !== "object") continue;
    const perTheme: Partial<Record<SessionMode, string>> = {};
    for (const [key, value] of Object.entries(entry as object)) {
      if (!isSessionMode(key) || !hasSessionSignature(key)) continue;
      if (typeof value !== "string") continue;
      const hex = normalizeHex(value);
      if (hex) perTheme[key] = hex;
    }
    if (Object.keys(perTheme).length > 0) clean[theme] = perTheme;
  }
  return Object.keys(clean).length > 0 ? clean : undefined;
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
  for (const theme of THEMES) {
    const perTheme = value[theme];
    if (!perTheme) continue;
    let body = "";
    // Iterate the known token list rather than the object's own keys, so the
    // emitted order is stable and nothing unvetted can reach the sheet.
    for (const token of ACCENT_TOKEN_NAMES) {
      const hex = perTheme[token] ? normalizeHex(perTheme[token]!) : null;
      if (hex) body += `--${token}:${hex};`;
    }
    if (body) css += `html[data-theme="${theme}"]{${body}}`;
  }
  // The session rules are more specific — (0,2,1) against (0,1,1) — so a mode
  // signature wins over a hand-set base accent in the same theme on specificity
  // rather than on which of the two happened to be written last.
  for (const theme of THEMES) {
    const perTheme = value[SESSION_KEY]?.[theme];
    if (!perTheme) continue;
    for (const sessionMode of SESSION_MODE_IDS) {
      if (!hasSessionSignature(sessionMode)) continue;
      const raw = perTheme[sessionMode];
      const hex = raw ? normalizeHex(raw) : null;
      if (!hex) continue;
      css += `html[data-theme="${theme}"][data-mode="${sessionMode}"]{--accent:${hex};}`;
    }
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
export function update(
  next: AccentOverrides,
  options?: { persist?: boolean },
): void {
  setOverridesSignal(next);
  applyOverrides(next);
  if (options?.persist !== false) persist(next);
}

/** Whether anything at all is overridden, in any theme — on either axis, so the
 *  RESET ALL control appears for a hand-set code accent as readily as for a
 *  hand-set alert red. */
export function hasAccentOverrides(): boolean {
  const value = overrides();
  return THEMES.some(
    (theme) =>
      Object.keys(value[theme] ?? {}).length > 0 ||
      Object.keys(value[SESSION_KEY]?.[theme] ?? {}).length > 0,
  );
}

/** Clear every override in every theme. Returns what was cleared, so the caller
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
