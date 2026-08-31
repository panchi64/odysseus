import { describe, expect, test } from "bun:test";
import {
  ACCENT_CONTRAST_FLOOR,
  MODE_BG,
  accentContrast,
  contrastRatio,
  meetsAccentFloor,
  normalizeHex,
  relativeLuminance,
} from "./contrast";
import { SESSION_MODE_IDS } from "~/lib/modes";
import {
  ACCENT_DEFAULTS,
  ACCENT_TOKENS,
  SESSION_ACCENT_DEFAULTS,
} from "./accents";

describe("normalizeHex", () => {
  test("expands 3-digit hex and lowercases", () => {
    expect(normalizeHex("#ABC")).toBe("#aabbcc");
    expect(normalizeHex("F0f")).toBe("#ff00ff");
  });

  test("accepts 6-digit hex with or without the hash, and trims", () => {
    expect(normalizeHex("  #34D67F ")).toBe("#34d67f");
    expect(normalizeHex("34d67f")).toBe("#34d67f");
  });

  test("rejects anything that is not a hex colour", () => {
    // The store concatenates the result into a stylesheet, so these must be
    // null rather than passed through — a `}` here would end the rule early.
    for (const junk of [
      "",
      "#12345",
      "#1234567",
      "red",
      "rgb(1,2,3)",
      "#ggg",
      "#000;}html{display:none",
    ])
      expect(normalizeHex(junk)).toBeNull();
  });
});

describe("relativeLuminance", () => {
  test("anchors at the sRGB extremes", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#ffffff")).toBe(1);
  });

  test("weights green above red above blue", () => {
    // The 0.2126/0.7152/0.0722 coefficients are the whole point of the
    // function; a fixture of one channel each is what would catch them being
    // transposed.
    const r = relativeLuminance("#ff0000")!;
    const g = relativeLuminance("#00ff00")!;
    const b = relativeLuminance("#0000ff")!;
    expect(g).toBeGreaterThan(r);
    expect(r).toBeGreaterThan(b);
    expect(g).toBeCloseTo(0.7152, 4);
    expect(r).toBeCloseTo(0.2126, 4);
    expect(b).toBeCloseTo(0.0722, 4);
  });

  test("uses the linear ramp below the 0.03928 knee", () => {
    // #050505 is 5/255 ≈ 0.0196, under the knee, so it must divide by 12.92
    // rather than take the 2.4 power. The two branches differ by ~2x here.
    expect(relativeLuminance("#050505")).toBeCloseTo(5 / 255 / 12.92, 6);
  });

  test("is null for a non-colour", () => {
    expect(relativeLuminance("nope")).toBeNull();
  });
});

describe("contrastRatio", () => {
  test("black on white is 21:1", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
  });

  test("a colour against itself is 1:1", () => {
    expect(contrastRatio("#34d67f", "#34d67f")).toBeCloseTo(1, 5);
  });

  test("is order-independent", () => {
    // The lighter colour must always be the numerator; swapping the arguments
    // returning a reciprocal would be the bug this catches.
    const a = contrastRatio("#34d67f", "#000000")!;
    const b = contrastRatio("#000000", "#34d67f")!;
    expect(a).toBeCloseTo(b, 10);
    expect(a).toBeGreaterThan(1);
  });

  test("is null when either side is not a colour", () => {
    expect(contrastRatio("#000000", "nope")).toBeNull();
    expect(contrastRatio("nope", "#000000")).toBeNull();
  });
});

describe("accentContrast", () => {
  test("measures against the mode's own background", () => {
    // Pure white: 21:1 on Ink's black, 1:1 on Paper's white. Same input, and
    // the answers must not resemble each other — that is what proves the mode
    // is actually selecting a background rather than being ignored.
    expect(accentContrast("#ffffff", "phosphor")).toBeCloseTo(21, 1);
    expect(accentContrast("#ffffff", "paper")).toBeCloseTo(1, 1);
  });

  test("rounds to one decimal for display", () => {
    const ratio = accentContrast("#34d67f", "phosphor")!;
    expect(ratio).toBe(Math.round(ratio * 10) / 10);
  });
});

describe("meetsAccentFloor", () => {
  test("separates a passing colour from a failing one", () => {
    // #767676 on white is ~4.54:1; #808080 is ~3.95:1. Both sit clear of the
    // rounding band, so this asserts the floor itself rather than where the
    // rounding lands.
    expect(meetsAccentFloor("#767676", "paper")).toBe(true);
    expect(meetsAccentFloor("#808080", "paper")).toBe(false);
  });

  test("the verdict agrees with the figure the field displays", () => {
    // #777777 on white is ~4.477:1, which displays as `4.5:1`. It passes, and
    // it has to: showing "4.5:1 — below the 4.5:1 floor" reads as a broken
    // interface. Checking the unrounded ratio here would produce exactly that,
    // so this test pins the rounding decision, not an arithmetic detail.
    expect(accentContrast("#777777", "paper")).toBe(4.5);
    expect(meetsAccentFloor("#777777", "paper")).toBe(true);
  });

  test("is exactly at the boundary for a ratio that rounds to the floor", () => {
    // The comparison must be `>=`, not `>` — a colour displaying exactly the
    // floor is the floor being met, not missed.
    expect(ACCENT_CONTRAST_FLOOR).toBe(4.5);
    expect(meetsAccentFloor("#757575", "paper")).toBe(true);
  });

  test("treats a non-colour as passing", () => {
    // An empty or half-typed field is not a contrast problem, and warning about
    // legibility there would point at the wrong thing.
    expect(meetsAccentFloor("", "phosphor")).toBe(true);
  });

  test("every shipped accent clears the floor in its own mode", () => {
    // §12 says the tokens are tuned to pass and must be re-verified after any
    // hue change. This is that verification, run on every commit.
    for (const mode of ["phosphor", "paper"] as const)
      for (const { token } of ACCENT_TOKENS) {
        const hex = ACCENT_DEFAULTS[mode][token];
        const ratio = accentContrast(hex, mode)!;
        expect(
          ratio,
          `${token} (${hex}) on ${mode} ${MODE_BG[mode]} is ${ratio}:1`,
        ).toBeGreaterThanOrEqual(ACCENT_CONTRAST_FLOOR);
      }
  });

  test("every shipped signature clears the floor in every session mode", () => {
    // The second axis, held to the same bar: a mode accent is the token the live
    // run, the composer edge and the blocking approval all paint with, so one
    // that fails 4.5:1 is illegible exactly where legibility matters most. Six
    // pairs — two themes by three modes — because a hue tuned for black is the
    // classic thing to forget to re-check on white.
    for (const mode of ["phosphor", "paper"] as const)
      for (const sessionMode of SESSION_MODE_IDS) {
        const hex = SESSION_ACCENT_DEFAULTS[mode][sessionMode];
        const ratio = accentContrast(hex, mode)!;
        expect(
          ratio,
          `${sessionMode} signature (${hex}) on ${mode} ${MODE_BG[mode]} is ${ratio}:1`,
        ).toBeGreaterThanOrEqual(ACCENT_CONTRAST_FLOOR);
      }
  });

  test("each mode's signature is genuinely its own", () => {
    // Three identical hexes would pass the floor check above while the feature
    // did nothing — the accent is what tells the operator which kind of thread
    // they are in, so the three have to differ.
    for (const mode of ["phosphor", "paper"] as const) {
      const hexes = SESSION_MODE_IDS.map(
        (sessionMode) => SESSION_ACCENT_DEFAULTS[mode][sessionMode],
      );
      expect(new Set(hexes).size, `${mode}: ${hexes.join(", ")}`).toBe(
        SESSION_MODE_IDS.length,
      );
    }
  });

  test("Normal's signature is the base accent, not a copy of it", () => {
    // Normal has no rule of its own in the cascade — it IS `--accent`. If this
    // ever diverged, retuning the shipped palette would move every mode except
    // the ordinary one.
    for (const mode of ["phosphor", "paper"] as const)
      expect(SESSION_ACCENT_DEFAULTS[mode].normal).toBe(
        ACCENT_DEFAULTS[mode].accent,
      );
  });
});
