import { describe, expect, test } from "bun:test";
import { NO_FLASH_SCRIPT } from "./no-flash";
import { serializeOverrides, type AccentOverrides } from "./accent-overrides";

/**
 * The pre-paint script is hand-written ES5 that rebuilds, by eye, what
 * `serializeOverrides` builds from types. It cannot import that function — it
 * runs before the bundle exists — so the duplication is unavoidable and this is
 * what keeps it honest: run the real script against stubbed globals and compare
 * its sheet to the store's, character for character.
 *
 * It is also the only test the script has at all, which matters because it
 * splices `localStorage` into a stylesheet. The injection cases below are the
 * point, not decoration.
 *
 * Pure by construction: the stubs are plain objects, so this stays inside the
 * "no DOM in `bun test`" rule without a jsdom.
 */

interface Painted {
  theme: string | undefined;
  css: string | null;
}

/** Execute the script with a fake window, and report what it painted. */
function paint(options: {
  theme?: string | null;
  accents?: unknown;
  systemPrefersLight?: boolean;
}): Painted {
  const store: Record<string, string> = {};
  if (options.theme != null) store["odysseus:theme"] = options.theme;
  if (options.accents !== undefined)
    store["odysseus:accents"] = JSON.stringify(options.accents);

  const root = { dataset: {} as Record<string, string> };
  // A one-slot box rather than a bare `let`, so reading it back after the script
  // has run doesn't require convincing the type checker that a callback fired.
  const appended: { el?: { id?: string; textContent?: string } } = {};
  const document = {
    documentElement: root,
    createElement: () => ({}) as Record<string, unknown>,
    head: {
      appendChild: (el: { id?: string; textContent?: string }) => {
        appended.el = el;
      },
    },
  };
  const window = {
    matchMedia: () => ({ matches: options.systemPrefersLight === true }),
  };
  const localStorage = {
    getItem: (key: string) => store[key] ?? null,
  };

  new Function("window", "document", "localStorage", NO_FLASH_SCRIPT)(
    window,
    document,
    localStorage,
  );

  return { theme: root.dataset.theme, css: appended.el?.textContent ?? null };
}

describe("the theme half", () => {
  test("applies a stored preference", () => {
    expect(paint({ theme: "paper" }).theme).toBe("paper");
  });

  test("resolves 'system' against the OS", () => {
    expect(paint({ theme: "system", systemPrefersLight: true }).theme).toBe(
      "paper",
    );
    expect(paint({ theme: "system", systemPrefersLight: false }).theme).toBe(
      "phosphor",
    );
  });

  test("falls back to phosphor for junk or nothing stored", () => {
    expect(paint({}).theme).toBe("phosphor");
    expect(paint({ theme: "chartreuse" }).theme).toBe("phosphor");
  });
});

describe("the accent half agrees with serializeOverrides", () => {
  const cases: Record<string, AccentOverrides> = {
    "a single token": { phosphor: { accent: "#112233" } },
    "both themes, several tokens": {
      phosphor: { accent: "#112233", "accent-warn": "#445566" },
      paper: { "accent-alert": "#778899" },
    },
    "a session signature": { sessionAccent: { phosphor: { code: "#b98cff" } } },
    "both axes at once": {
      phosphor: { accent: "#111111" },
      paper: { "accent-info": "#222222" },
      sessionAccent: {
        phosphor: { research: "#3ddbd9", code: "#b98cff" },
        paper: { code: "#6d28d9" },
      },
    },
  };

  for (const [name, overrides] of Object.entries(cases))
    test(name, () => {
      expect(paint({ accents: overrides }).css).toBe(
        serializeOverrides(overrides),
      );
    });

  test("writes no sheet at all when nothing is overridden", () => {
    // An empty `<style>` in every document is litter, and the store's own
    // `applyOverrides` declines to add one for the same reason.
    expect(paint({ accents: {} }).css).toBeNull();
    expect(paint({}).css).toBeNull();
  });
});

describe("the accent half refuses what the store refuses", () => {
  test("a value that would close the rule and open its own", () => {
    const css = paint({
      accents: {
        phosphor: {
          accent: "#000;}html{display:none",
          "accent-warn": "#f2a93b",
        },
      },
    }).css;
    expect(css).not.toContain("display:none");
    expect(css).toBe('html[data-theme="phosphor"]{--accent-warn:#f2a93b;}');
  });

  test("the same injection through the session axis", () => {
    const css = paint({
      accents: {
        sessionAccent: { phosphor: { code: "#000;}html{display:none" } },
      },
    }).css;
    expect(css).toBeNull();
  });

  test("a key that is not an accent token", () => {
    // A `--bg` override would repaint the entire product from localStorage.
    const css = paint({ accents: { phosphor: { bg: "#ff0000" } } }).css;
    expect(css).toBeNull();
  });

  test("a session mode this build does not have", () => {
    const css = paint({
      accents: { sessionAccent: { phosphor: { admin: "#ff0000" } } },
    }).css;
    expect(css).toBeNull();
  });

  test("Normal, which has no rule of its own", () => {
    const css = paint({
      accents: { sessionAccent: { phosphor: { normal: "#ff0000" } } },
    }).css;
    expect(css).toBeNull();
  });

  test("a stored blob that is not an object at all", () => {
    expect(paint({ accents: "nope" }).css).toBeNull();
    expect(paint({ accents: null }).css).toBeNull();
  });
});
