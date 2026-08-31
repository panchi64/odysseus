import { describe, expect, test } from "bun:test";
import { createAccentAxis, readAt, writeAt } from "./accent-axis";
import type { AccentOverrides } from "./accent-overrides";

/**
 * The two accent stores are now one set of rules over two paths, so this tests the
 * rules — at both depths, because the depth is the only thing that ever differed and
 * the deeper one is where the unwind used to be written out by hand.
 *
 * Pure by construction: the store handle below is a variable, so none of this needs a
 * `localStorage` or a `document`.
 */

const BASE = { path: () => ["phosphor"] as const, shipped: () => "#34d67f" };
const SESSION = {
  path: () => ["sessionAccent", "phosphor"] as const,
  shipped: () => "#b98cff",
};

/** An in-memory stand-in for `accent-overrides`' signal + `update`. */
function harness() {
  let held: AccentOverrides = {};
  return {
    handle: {
      read: () => held,
      update: (next: AccentOverrides) => {
        held = next;
      },
    },
    get: () => held,
  };
}

describe("an override reads back, at either depth", () => {
  test("the shipped value until something is set", () => {
    const h = harness();
    const axis = createAccentAxis(BASE, h.handle);
    expect(axis.value("phosphor", "accent")).toBe("#34d67f");
    expect(axis.isOverridden("phosphor", "accent")).toBe(false);
    axis.set("phosphor", "accent", "#112233");
    expect(axis.value("phosphor", "accent")).toBe("#112233");
    expect(axis.isOverridden("phosphor", "accent")).toBe(true);
  });

  test("and the same one key level deeper", () => {
    const h = harness();
    const axis = createAccentAxis(SESSION, h.handle);
    axis.set("phosphor", "code", "#112233");
    expect(h.get()).toEqual({
      sessionAccent: { phosphor: { code: "#112233" } },
    });
    expect(axis.value("phosphor", "code")).toBe("#112233");
  });

  test("a value that is not a colour is refused outright", () => {
    const h = harness();
    createAccentAxis(BASE, h.handle).set(
      "phosphor",
      "accent",
      "#000;}html{display:none",
    );
    expect(h.get()).toEqual({});
  });
});

describe("clearing leaves nothing behind — the reason it is written once", () => {
  test("resetting prunes the level it emptied", () => {
    // Not cosmetic: `hasAccentOverrides` answers by counting keys, so an empty map
    // left behind keeps the RESET ALL control on screen with nothing to reset.
    const h = harness();
    const axis = createAccentAxis(BASE, h.handle);
    axis.set("phosphor", "accent", "#112233");
    axis.reset("phosphor", "accent");
    expect(h.get()).toEqual({});
  });

  test("and prunes EVERY level it emptied on the deeper axis", () => {
    // The case the hand-written session store had to unwind twice by hand.
    const h = harness();
    const axis = createAccentAxis(SESSION, h.handle);
    axis.set("phosphor", "code", "#112233");
    axis.reset("phosphor", "code");
    expect(h.get()).toEqual({});
  });

  test("a sibling on the same level survives the prune", () => {
    const h = harness();
    const axis = createAccentAxis(SESSION, h.handle);
    axis.set("phosphor", "code", "#112233");
    axis.set("phosphor", "research", "#445566");
    axis.reset("phosphor", "code");
    expect(h.get()).toEqual({
      sessionAccent: { phosphor: { research: "#445566" } },
    });
  });

  test("setting a key back to its shipped value clears rather than stores it", () => {
    // Otherwise "I set it back by hand" and "I pressed reset" leave different
    // states, and the reset control lingers beside a key overriding nothing.
    const h = harness();
    const axis = createAccentAxis(BASE, h.handle);
    axis.set("phosphor", "accent", "#112233");
    axis.set("phosphor", "accent", "#34D67F"); // the shipped value, shouted
    expect(h.get()).toEqual({});
    expect(axis.isOverridden("phosphor", "accent")).toBe(false);
  });
});

describe("the walk survives whatever localStorage holds", () => {
  test("a blob of the wrong shape reads as nothing", () => {
    expect(readAt("nope", ["phosphor"])).toBeUndefined();
    expect(readAt(null, ["sessionAccent", "phosphor"])).toBeUndefined();
    expect(
      readAt({ sessionAccent: 7 }, ["sessionAccent", "phosphor"]),
    ).toBeUndefined();
  });

  test("writing a path whose parents do not exist yet builds them", () => {
    expect(
      writeAt({}, ["sessionAccent", "paper"], { code: "#112233" }),
    ).toEqual({
      sessionAccent: { paper: { code: "#112233" } },
    });
  });
});
