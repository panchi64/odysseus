import { describe, expect, test } from "bun:test";
import { SETTINGS_CATEGORIES, allSectionIds, categoryById } from "./categories";
import { legacySettingsHref, SETTINGS_PARAM } from "./legacy";

describe("the category model", () => {
  test("every category is addressable and describable", () => {
    for (const category of SETTINGS_CATEGORIES) {
      expect(category.id).toMatch(/^[a-z][a-z-]*$/);
      expect(category.label.length).toBeGreaterThan(0);
      expect(category.description.length).toBeGreaterThan(0);
      expect(category.sections.length).toBeGreaterThan(0);
    }
  });

  test("ids are unique, across categories and across sections", () => {
    const ids = SETTINGS_CATEGORIES.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    const sections = allSectionIds();
    expect(new Set(sections).size).toBe(sections.length);
  });

  test("a section id is namespaced by the category that owns it", () => {
    // Not decoration: the id is what a deep link and a renderer key both name,
    // and a bare `health` under two categories would be two different panes
    // answering to one key.
    for (const category of SETTINGS_CATEGORIES)
      for (const section of category.sections)
        expect(section.startsWith(`${category.id}.`)).toBe(true);
  });

  test("an unknown or missing id lands on the first category", () => {
    // A stale bookmark and a hand-typed slug both open the dialog rather than an
    // empty pane — the failure mode this fallback exists to prevent.
    expect(categoryById(undefined).id).toBe(SETTINGS_CATEGORIES[0].id);
    expect(categoryById("no-such-category").id).toBe(SETTINGS_CATEGORIES[0].id);
    expect(categoryById("security").id).toBe("security");
  });
});

describe("legacySettingsHref", () => {
  test("every retired page forwards to a category that exists", () => {
    // The map is hand-written, so nothing but this stops a typo pointing a
    // redirect at a category that was renamed — which would silently land on
    // GENERAL instead of the intended pane.
    const known = new Set(SETTINGS_CATEGORIES.map((c) => c.id));
    for (const path of [
      "/settings",
      "/settings/appearance",
      "/settings/tools",
      "/settings/models",
      "/skills",
      "/projects",
      "/memory",
      "/vault",
      "/admin/tokens",
      "/admin/access-tokens",
      "/integrations",
      "/backup",
      "/health",
    ]) {
      const href = legacySettingsHref(path);
      expect(href).toBeDefined();
      expect(known.has(href!.split("=")[1])).toBe(true);
    }
  });

  test("the forward carries the same param the dialog reads", () => {
    expect(legacySettingsHref("/vault")).toBe(`/?${SETTINGS_PARAM}=security`);
  });

  test("a deep path under a retired page resolves to that page", () => {
    // `/skills/abc` was the editor. The surface is gone, so the whole subtree
    // forwards rather than 404ing on the child alone.
    expect(legacySettingsHref("/skills/abc")).toBe(
      legacySettingsHref("/skills"),
    );
    expect(legacySettingsHref("/settings/appearance/")).toBe(
      legacySettingsHref("/settings/appearance"),
    );
  });

  test("a path that was never a settings page is left to 404", () => {
    // The redirect must not swallow a genuine typo — `/chat` and `/research`
    // are live routes, and `/nonsense` should read as missing.
    expect(legacySettingsHref("/nonsense")).toBeUndefined();
    expect(legacySettingsHref("/chat")).toBeUndefined();
    expect(legacySettingsHref("/research")).toBeUndefined();
    expect(legacySettingsHref("/")).toBeUndefined();
  });

  test("a live route that merely starts like a retired one is left alone", () => {
    // `/backups-of-something` starts with `/backup` as a string but is not a
    // child of it — the prefix test has to be on a path segment, not characters.
    expect(legacySettingsHref("/backups-of-something")).toBeUndefined();
  });
});
