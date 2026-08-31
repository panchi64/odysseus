import type { SessionMode } from "~/lib/modes";
import type { ThemeMode } from "./theme-store";

/** The five accent tokens, by their CSS custom-property name minus the `--`.
 *  This list is closed: an accent is a *meaning* (§5.2), and the set of meanings
 *  is a design decision, not a preference. What the operator chooses is the hue
 *  each meaning wears — see `accent-store`. */
export type AccentToken =
  "accent" | "accent-nominal" | "accent-warn" | "accent-alert" | "accent-info";

export interface AccentTokenSpec {
  token: AccentToken;
  /** Sentence case — the interface naming the thing to the operator (§2). */
  label: string;
  /** What this accent *means*. The meaning is fixed even though the hue is not,
   *  so this doubles as the argument against setting `alert` to green. */
  description: string;
}

/** Render order for the editor: the signature first, then the four semantics in
 *  the order §5 lists them. */
export const ACCENT_TOKENS: readonly AccentTokenSpec[] = [
  {
    token: "accent",
    label: "Signature",
    description:
      "Primary focus — the live run, the awaiting-approval card. At most one per screen.",
  },
  {
    token: "accent-nominal",
    label: "Nominal",
    description: "Healthy, complete, connected.",
  },
  {
    token: "accent-warn",
    label: "Warning",
    description: "Degraded, nearing a limit, needs attention but not action.",
  },
  {
    token: "accent-alert",
    label: "Alert",
    description: "Failed, blocked, or genuinely wrong.",
  },
  {
    token: "accent-info",
    label: "Info",
    description: "Live data and secondary signal — streaming, in flight.",
  },
];

/**
 * The shipped value of every accent, per mode — **the same hexes tokens.css
 * declares**, and the reason `accents.test.ts` parses that file and asserts
 * they still match.
 *
 * Duplicating them here is deliberate and the test is what makes it safe. The
 * store needs to know a token's default in order to answer two questions the
 * cascade cannot: *is this one overridden* (so the reset control appears), and
 * *what does the swatch show before anything is chosen*. It cannot read them
 * back out of `getComputedStyle`, because by the time any of this runs the
 * no-flash script has already applied the overrides on top — the cascade holds
 * the current value, which is exactly not the default.
 *
 * The mode-dependence is §5.2's, not an accident: phosphor green belongs on
 * black and turns acidic on white, so Ink and Paper carry different values for
 * four of the five and are overridden separately.
 */
export const ACCENT_DEFAULTS: Record<ThemeMode, Record<AccentToken, string>> = {
  phosphor: {
    accent: "#34d67f",
    "accent-nominal": "#34d67f",
    "accent-warn": "#f2a93b",
    "accent-alert": "#ff5c5c",
    "accent-info": "#5aa2ff",
  },
  paper: {
    accent: "#0077b6",
    "accent-nominal": "#0e7a46",
    "accent-warn": "#9a6510",
    "accent-alert": "#c0342b",
    "accent-info": "#0f5fa8",
  },
};

/**
 * The signature accent per (theme, session mode) — **the same hexes tokens.css
 * declares** in its SESSION MODE block, mirrored here for the same reason
 * `ACCENT_DEFAULTS` is: the store has to tell "overridden" from "untouched", and
 * the cascade cannot answer that once an override is applied on top of it.
 *
 * Only `accent` appears here, and that is a design decision rather than a
 * shortcut. The other four are a closed set of *meanings*; rebinding "alert" per
 * mode would make red mean something different depending on which thread you are
 * looking at. The signature token is the one whose job is to say *where you
 * are*, so the mode is exactly the thing it should carry.
 *
 * Normal resolves to `ACCENT_DEFAULTS[theme].accent` — the base value, not a
 * copy of it, so retuning the shipped palette moves the ordinary mode with it.
 */
export const SESSION_ACCENT_DEFAULTS: Record<
  ThemeMode,
  Record<SessionMode, string>
> = {
  phosphor: {
    normal: ACCENT_DEFAULTS.phosphor.accent,
    research: "#3ddbd9",
    code: "#b98cff",
  },
  paper: {
    normal: ACCENT_DEFAULTS.paper.accent,
    research: "#0e7490",
    code: "#6d28d9",
  },
};

/** Whether this (theme, session mode) pair carries a signature of its own, or
 *  simply inherits the base palette. Normal is the base by construction, so it
 *  never needs a rule emitted for it. */
export function hasSessionSignature(mode: SessionMode): boolean {
  return mode !== "normal";
}

/** The set, for validating whatever comes back out of localStorage. */
export const ACCENT_TOKEN_NAMES: readonly AccentToken[] = ACCENT_TOKENS.map(
  (spec) => spec.token,
);

export function isAccentToken(value: string): value is AccentToken {
  return (ACCENT_TOKEN_NAMES as readonly string[]).includes(value);
}
