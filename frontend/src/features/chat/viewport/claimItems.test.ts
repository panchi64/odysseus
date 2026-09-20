import { describe, expect, test } from "bun:test";
import { collectClaims, NO_CLAIMS } from "./claimItems";
import type { Claim, MessageAttribution } from "../data/attributions";

function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    claim: "the build is green",
    grounded: true,
    sourceKey: "https://a.example/one",
    sourceTitle: "One",
    sourceUrl: "https://a.example/one",
    sourceKind: "web",
    passage: "the build is green",
    confidence: "medium",
    offset: null,
    ...overrides,
  };
}

function turn(claims: Claim[], overrides: Partial<MessageAttribution> = {}) {
  return {
    messageId: "m-1",
    extractedAt: "2026-09-20T10:00:00Z",
    claims,
    ...overrides,
  };
}

describe("collectClaims", () => {
  test("an ungrounded claim leads, whatever order it arrived in", () => {
    // Ordered to fight the rule: the grounded one is first in the payload.
    const inv = collectClaims([
      turn([
        claim({ claim: "supported" }),
        claim({ claim: "unsupported", grounded: false, passage: null }),
      ]),
    ]);
    expect(inv.items.map((r) => r.claim)).toEqual(["unsupported", "supported"]);
    expect(inv.ungroundedCount).toBe(1);
  });

  test("two sources behind one claim fold into one row and count as two origins", () => {
    // The figure the message-level inventory cannot give: corroboration for *this*
    // assertion rather than for the thread.
    const inv = collectClaims([
      turn([
        claim({
          claim: "x",
          sourceKey: "https://a.example/1",
          sourceUrl: "https://a.example/1",
        }),
        claim({
          claim: "x",
          sourceKey: "https://b.example/2",
          sourceUrl: "https://b.example/2",
        }),
      ]),
    ]);
    expect(inv.items).toHaveLength(1);
    expect(inv.items[0].sources).toHaveLength(2);
    expect(inv.items[0].origins).toBe(2);
  });

  test("two pages off one site are two sources but one origin", () => {
    // The same honesty the inventory's own origin count keeps — otherwise a claim
    // reads as twice the corroboration it has.
    const inv = collectClaims([
      turn([
        claim({
          claim: "x",
          sourceKey: "https://a.example/1",
          sourceUrl: "https://a.example/1",
        }),
        claim({
          claim: "x",
          sourceKey: "https://a.example/2",
          sourceUrl: "https://a.example/2",
        }),
      ]),
    ]);
    expect(inv.items[0].sources).toHaveLength(2);
    expect(inv.items[0].origins).toBe(1);
  });

  test("the same source twice under one claim counts once", () => {
    const inv = collectClaims([
      turn([claim({ claim: "x" })]),
      turn([claim({ claim: "x" })], { messageId: "m-2" }),
    ]);
    expect(inv.items[0].sources).toHaveLength(1);
    expect(inv.items[0].origins).toBe(1);
  });

  test("a claim one source supports and another does not is grounded, with both listed", () => {
    // Grounded-with-a-weak-source is a different thing from ungrounded, and burying
    // the second source would hide exactly what the operator came to see.
    const inv = collectClaims([
      turn([
        claim({
          claim: "x",
          grounded: false,
          passage: null,
          sourceKey: "k1",
          sourceUrl: "https://a.example/1",
        }),
        claim({
          claim: "x",
          grounded: true,
          sourceKey: "k2",
          sourceUrl: "https://b.example/2",
        }),
      ]),
    ]);
    expect(inv.items[0].grounded).toBe(true);
    expect(inv.items[0].sources).toHaveLength(2);
    expect(inv.ungroundedCount).toBe(0);
  });

  test("the strongest confidence across sightings wins", () => {
    const inv = collectClaims([
      turn([
        claim({ claim: "x", confidence: "low", sourceKey: "k1" }),
        claim({ claim: "x", confidence: "high", sourceKey: "k2" }),
        claim({ claim: "x", confidence: "medium", sourceKey: "k3" }),
      ]),
    ]);
    expect(inv.items[0].confidence).toBe("high");
  });

  test("a claim with no nameable source still gets a row, contributing no origin", () => {
    const inv = collectClaims([
      turn([
        claim({
          claim: "x",
          grounded: false,
          sourceKey: null,
          sourceTitle: null,
          sourceUrl: null,
          sourceKind: null,
          passage: null,
        }),
      ]),
    ]);
    expect(inv.items).toHaveLength(1);
    expect(inv.items[0].sources).toEqual([]);
    expect(inv.items[0].origins).toBe(0);
  });

  test("a corpus source counts as an origin by its title", () => {
    const inv = collectClaims([
      turn([
        claim({
          claim: "x",
          sourceKey: "notes:a.md",
          sourceTitle: "notes",
          sourceUrl: null,
          sourceKind: "corpus",
        }),
      ]),
    ]);
    expect(inv.items[0].origins).toBe(1);
  });

  test("near-identical sentences stay two claims", () => {
    // Deliberately strict. Overcounting claims is readable; silently merging two
    // assertions is this layer deciding the model said the same thing twice.
    const inv = collectClaims([
      turn([
        claim({ claim: "the build is green" }),
        claim({ claim: "the build is green." }),
      ]),
    ]);
    expect(inv.items).toHaveLength(2);
  });

  test("an empty reading is the ordinary answer, not a zero-row heading", () => {
    expect(collectClaims([])).toEqual(NO_CLAIMS);
    // A turn that produced no claims does not count as a turn with a reading.
    expect(collectClaims([turn([])]).turns).toBe(0);
  });

  test("the newest extraction stamp wins across turns", () => {
    const inv = collectClaims([
      turn([claim()], { extractedAt: "2026-09-19T10:00:00Z" }),
      turn([claim({ claim: "y" })], {
        messageId: "m-2",
        extractedAt: "2026-09-20T10:00:00Z",
      }),
    ]);
    expect(inv.newestExtraction).toBe("2026-09-20T10:00:00Z");
    expect(inv.turns).toBe(2);
  });

  test("a blank claim is dropped rather than folded into one empty row", () => {
    const inv = collectClaims([
      turn([claim({ claim: "   " }), claim({ claim: "real" })]),
    ]);
    expect(inv.items.map((r) => r.claim)).toEqual(["real"]);
  });
});
