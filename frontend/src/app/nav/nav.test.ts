/**
 * The nav model's derivations. Everything here is pure — `areas` is injectable
 * on every function precisely so the rules can be exercised against a fixture
 * rather than against whatever the real rail happens to contain today.
 *
 * Two kinds of test live here, and the split is deliberate:
 *  - Behaviour, against `FIXTURE`, so a test fails when a rule changes rather
 *    than when a page is added.
 *  - Invariants, against the real `AREAS`/`PINS`, because those are claims the
 *    rail's documentation makes about the actual data and nothing else checks.
 */
import { describe, expect, test } from "bun:test";
import {
  AREAS,
  PINS,
  areaForPath,
  flattenNav,
  isConnectedRoute,
  itemForPath,
  searchNav,
} from "./index";
import type { NavArea } from "./types";

const item = (
  label: string,
  href: string,
  opts: { connected?: boolean; description?: string } = {},
) => ({
  label,
  href,
  icon: "file" as const,
  description: opts.description ?? `${label} description`,
  ...(opts.connected === undefined ? {} : { connected: opts.connected }),
});

/** Shaped so each rule is exercised by data that would break if the rule were
 *  dropped — a fixture that merely resembles the real rail passes either way.
 *  The real rail has no prefix pair at all today, so `/docs` + `/docs/drafts`
 *  exist only here. */
const FIXTURE: NavArea[] = [
  {
    id: "alpha",
    label: "ALPHA",
    icon: "file",
    description: "alpha area",
    items: [
      // Declared BEFORE its own parent, deliberately: declaration order and
      // longest-match disagree about /docs/drafts, so first-wins and last-wins
      // both resolve it differently than longest-wins does.
      item("Drafts", "/docs/drafts", { connected: true }),
      item("Docs", "/docs", { connected: true }),
      item("Mock", "/mock"),
    ],
  },
  {
    id: "beta",
    label: "BETA",
    icon: "file",
    description: "beta area",
    items: [
      item("Other", "/other", { connected: true }),
      // No "drafts" in the label, "drafts" in the description — the pair that
      // makes label-before-description ranking observable.
      item("Archive", "/archive", {
        connected: true,
        description: "Where drafts go to rest",
      }),
      // Nothing owns the bare /group segment, mirroring how /settings is only
      // ever a redirect into its first section. The parent-of-connected-children
      // branch is the ONLY thing that can resolve it.
      item("Section", "/group/section", { connected: true }),
    ],
  },
];

describe("areaForPath", () => {
  test("longest match wins, so a nested page keeps its own area", () => {
    expect(areaForPath("/docs", FIXTURE)?.id).toBe("alpha");
    expect(itemForPath("/docs/drafts", FIXTURE)?.href).toBe("/docs/drafts");
    // Without longest-match this lands on /docs, and the deeper page can never
    // be the active item.
    expect(itemForPath("/docs/drafts/2024", FIXTURE)?.href).toBe(
      "/docs/drafts",
    );
  });

  test("a detail route resolves to its parent page", () => {
    expect(itemForPath("/docs/abc123", FIXTURE)?.href).toBe("/docs");
  });

  test("matching is segment-bounded, not a bare prefix", () => {
    // /docs must not claim /docs-archive.
    expect(areaForPath("/docs-archive", FIXTURE)).toBeUndefined();
  });

  test("returns undefined rather than guessing an area", () => {
    expect(areaForPath("/", FIXTURE)).toBeUndefined();
    expect(areaForPath("/unlisted", FIXTURE)).toBeUndefined();
  });
});

describe("flattenNav", () => {
  test("keeps a pin that no area owns and drops one that shortcuts into an area", () => {
    const hrefs = flattenNav(AREAS).map((m) => m.item.href);
    const areaOwned = new Set(AREAS.flatMap((a) => a.items.map((i) => i.href)));

    for (const pin of PINS) {
      const occurrences = hrefs.filter((h) => h === pin.item.href).length;
      expect(occurrences).toBe(1);
      // An area-owned pin appears once via its area (with an `area`); a
      // standalone pin appears once as a pin (without one).
      const match = flattenNav(AREAS).find(
        (m) => m.item.href === pin.item.href,
      );
      expect(match?.area === undefined).toBe(!areaOwned.has(pin.item.href));
    }
  });
});

describe("isConnectedRoute", () => {
  test("the home route is connected despite having no nav entry", () => {
    expect(isConnectedRoute("/", FIXTURE)).toBe(true);
  });

  test("an unconnected page is not, and neither is an unlisted route", () => {
    expect(isConnectedRoute("/mock", FIXTURE)).toBe(false);
    expect(isConnectedRoute("/unlisted", FIXTURE)).toBe(false);
  });

  test("a parent of connected children counts, so a redirect doesn't flash the overlay", () => {
    // No item owns /group; only /group/section does. This passes solely on the
    // parent branch — /docs would not prove it, since /docs is an item itself.
    expect(isConnectedRoute("/group", FIXTURE)).toBe(true);
  });

  test("a surface that became a settings section is not a route", () => {
    // These have no nav item and no route: configuration is reached through the
    // dialog, so `/settings` and `/vault` are dead paths that read as dead.
    expect(AREAS.flatMap((a) => a.items).some((i) => i.href === "/settings")) //
      .toBe(false);
    expect(isConnectedRoute("/settings")).toBe(false);
    expect(isConnectedRoute("/vault")).toBe(false);
  });
});

describe("searchNav", () => {
  test("an empty query returns nothing", () => {
    expect(searchNav("", FIXTURE)).toEqual([]);
    expect(searchNav("   ", FIXTURE)).toEqual([]);
  });

  test("label matches rank ahead of description matches", () => {
    // "drafts" is Drafts' label and Archive's description. Both must come back,
    // label hit first — otherwise typing a page's name surfaces some other page.
    const results = searchNav("drafts", FIXTURE);
    expect(results.map((m) => m.item.href)).toEqual([
      "/docs/drafts",
      "/archive",
    ]);
  });

  test("an item is counted once, by its label, even when both fields match", () => {
    // Drafts' generated description contains "drafts" too; the else-if must not
    // let it land in both buckets.
    expect(
      searchNav("drafts", FIXTURE).filter(
        (m) => m.item.href === "/docs/drafts",
      ),
    ).toHaveLength(1);
  });

  test("matches descriptions, so a surface is findable by what it does", () => {
    expect(searchNav("description", FIXTURE).length).toBeGreaterThan(0);
  });

  test("is case-insensitive", () => {
    expect(searchNav("DOCS", FIXTURE).map((m) => m.item.href)).toContain(
      "/docs",
    );
  });
});

describe("the real nav data", () => {
  test("an href appears in at most one area", () => {
    const seen = new Map<string, string>();
    const collisions: string[] = [];
    for (const area of AREAS) {
      for (const navItem of area.items) {
        const owner = seen.get(navItem.href);
        if (owner) collisions.push(`${navItem.href}: ${owner} and ${area.id}`);
        else seen.set(navItem.href, area.id);
      }
    }
    expect(collisions).toEqual([]);
  });

  test("every area and item is non-empty and describable", () => {
    expect(AREAS.length).toBeGreaterThan(0);
    for (const area of AREAS) {
      expect(area.items.length).toBeGreaterThan(0);
      for (const navItem of area.items) {
        expect(navItem.href.startsWith("/")).toBe(true);
        expect(navItem.label.length).toBeGreaterThan(0);
        expect(navItem.description.length).toBeGreaterThan(0);
      }
    }
  });

  test("every area resolves from its own first item's path", () => {
    for (const area of AREAS) {
      expect(areaForPath(area.items[0]!.href)?.id).toBe(area.id);
    }
  });

  test("every remaining nav surface is wired to the backend", () => {
    // Health was the one exception, and it is no longer a route: it is a section
    // of the settings dialog, which renders its own inline NOT CONNECTED overlay
    // (see HealthScreen). Nothing reachable from the rail is on fixtures, so
    // this list is empty — and if an unwired surface is ever added to the nav,
    // this is what says so.
    const unconnected = flattenNav()
      .filter((m) => !m.item.connected)
      .map((m) => m.item.href);
    expect(unconnected).toEqual([]);
  });
});
