import { describe, expect, test } from "bun:test";
import {
  ACCENT_DEFAULTS,
  ACCENT_TOKENS,
  SESSION_ACCENT_DEFAULTS,
  hasSessionSignature,
  isAccentToken,
} from "./accents";

/**
 * `ACCENT_DEFAULTS` restates hexes that tokens.css already declares, because the
 * store needs to know a token's shipped value in order to tell "overridden" from
 * "untouched" — and it cannot read that back out of the cascade, which by then
 * holds the override. Duplication is the price; this file is what makes it safe.
 *
 * It parses tokens.css rather than importing it, since a stylesheet has no
 * runtime export. That keeps the test pure (one file read, no DOM), which is the
 * bar `frontend/CLAUDE.md` sets for what may live in `bun test`.
 */

const CSS = await Bun.file(
  new URL("./tokens.css", import.meta.url).pathname,
).text();

/** tokens.css scopes Ink to `:root` and Paper to `[data-theme="paper"]`. Slice
 *  the file at the Paper selector: everything before it is Ink's block, and the
 *  accents are declared once in each.
 *
 *  Anchored to the start of a line, because the selector is also *named in a
 *  comment* at the top of the file — matching that instead put the whole Ink
 *  block on Paper's side of the cut and made every Paper token read Ink's
 *  value. */
function blockFor(mode: "phosphor" | "paper"): string {
  const paperAt = CSS.search(/^\[data-theme="paper"\]\s*\{/m);
  expect(paperAt).toBeGreaterThan(-1);
  return mode === "phosphor" ? CSS.slice(0, paperAt) : CSS.slice(paperAt);
}

function declaredValue(
  mode: "phosphor" | "paper",
  token: string,
): string | null {
  // `--accent:` must not match `--accent-warn:`, so the boundary is explicit.
  const match = blockFor(mode).match(
    new RegExp(`--${token}\\s*:\\s*(#[0-9a-fA-F]{3,8})\\s*;`),
  );
  return match ? match[1].toLowerCase() : null;
}

describe("ACCENT_DEFAULTS mirrors tokens.css", () => {
  test("the stylesheet was actually read", () => {
    // Without this, a bad path would make every assertion below vacuous.
    expect(CSS.length).toBeGreaterThan(1000);
    expect(CSS).toContain("--accent:");
  });

  for (const mode of ["phosphor", "paper"] as const)
    for (const { token } of ACCENT_TOKENS)
      test(`${mode} · ${token}`, () => {
        expect(declaredValue(mode, token)).toBe(ACCENT_DEFAULTS[mode][token]);
      });

  test("the two modes genuinely differ", () => {
    // Guards the slicing above: if `blockFor` returned the same text twice,
    // every per-token assertion would still pass. §5.2 says the signature
    // accent is mode-dependent, so these must not be equal.
    expect(ACCENT_DEFAULTS.phosphor.accent).not.toBe(
      ACCENT_DEFAULTS.paper.accent,
    );
    expect(declaredValue("phosphor", "accent")).not.toBe(
      declaredValue("paper", "accent"),
    );
  });
});

/** The value a `[data-theme=…][data-mode=…]` rule declares for `--accent`, or
 *  null when tokens.css has no such rule. Matched on the whole rule rather than
 *  sliced out of a block: these are standalone one-declaration rules, not part
 *  of either theme's token block. */
function declaredSessionAccent(
  mode: "phosphor" | "paper",
  sessionMode: string,
): string | null {
  const match = CSS.match(
    new RegExp(
      `\\[data-theme="${mode}"\\]\\[data-mode="${sessionMode}"\\]\\s*\\{[^}]*--accent\\s*:\\s*(#[0-9a-fA-F]{3,8})\\s*;`,
    ),
  );
  return match ? match[1].toLowerCase() : null;
}

describe("SESSION_ACCENT_DEFAULTS mirrors tokens.css", () => {
  for (const mode of ["phosphor", "paper"] as const)
    for (const sessionMode of ["research", "code"] as const)
      test(`${mode} · ${sessionMode}`, () => {
        expect(declaredSessionAccent(mode, sessionMode)).toBe(
          SESSION_ACCENT_DEFAULTS[mode][sessionMode],
        );
      });

  test("Normal has no rule of its own", () => {
    // It is the base `--accent`, and a `[data-mode="normal"]` rule would be a
    // second declaration of the same token — the serializer refuses to emit one
    // for exactly this reason, and the stylesheet must not contain one either.
    for (const mode of ["phosphor", "paper"] as const)
      expect(declaredSessionAccent(mode, "normal")).toBeNull();
  });
});

describe("hasSessionSignature", () => {
  test("is true for every mode except Normal", () => {
    expect(hasSessionSignature("normal")).toBe(false);
    expect(hasSessionSignature("research")).toBe(true);
    expect(hasSessionSignature("code")).toBe(true);
  });
});

describe("isAccentToken", () => {
  test("accepts every listed token and nothing else", () => {
    for (const { token } of ACCENT_TOKENS)
      expect(isAccentToken(token)).toBe(true);
    for (const other of ["bg", "text", "accent-", "--accent", "accent-nope"])
      expect(isAccentToken(other)).toBe(false);
  });
});
