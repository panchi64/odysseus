import { describe, expect, test } from "bun:test";
import { asCompactionReason, compactionReasonCause } from "./compactionReason";
import type { CompactionReason } from "./model";

const ALL: CompactionReason[] = ["threshold", "overflow", "manual"];

describe("every reason the wire can send has words", () => {
  // A missing entry renders `undefined` into the panel's row, which is worse than saying
  // nothing: the separator stays and the operator reads a fold with a blank cause. The map
  // is keyed by the union, so this is really a guard against a *value* being added to the
  // union with no wording behind it.
  test("all three are worded", () => {
    for (const reason of ALL)
      expect(compactionReasonCause(reason)).toBeTruthy();
  });

  test("no two reasons read the same", () => {
    // The whole point of carrying the reason is that a fold the operator asked for, a fold
    // at their threshold and a fold the provider forced are different events. Two of them
    // sharing a phrase would put that distinction back where it was.
    expect(new Set(ALL.map(compactionReasonCause)).size).toBe(ALL.length);
  });

  test("each is a stated fact, not a sentence addressed to the operator", () => {
    // The panel is a console readout in the machine register, where a line that turns
    // round and speaks to the reader is the one thing that breaks it. Lower case because
    // the value sits after a `·` in a row, and no period because it is a label.
    for (const reason of ALL) {
      const cause = compactionReasonCause(reason);
      expect(cause[0]).toBe(cause[0].toLowerCase());
      expect(cause.endsWith(".")).toBe(false);
      expect(cause).not.toMatch(/\byou\b/i);
    }
  });
});

describe("narrowing the cold read's plain string", () => {
  // The conversation detail carries the reason as a bare string, so this is the gate
  // between the wire and a `Record` lookup that would otherwise return `undefined` and
  // print it into the label.
  test("every reason with words survives", () => {
    for (const reason of ALL) expect(asCompactionReason(reason)).toBe(reason);
  });

  test("a reason this build cannot word is dropped, not passed through", () => {
    // A checkpoint folded before the backend recorded reasons sends null; a newer backend
    // could name a trigger this build has never heard of. Both have the same right answer
    // — fall back to the ordinary trigger — where a raw enum id on screen would not.
    expect(asCompactionReason(null)).toBeUndefined();
    expect(asCompactionReason(undefined)).toBeUndefined();
    expect(asCompactionReason("")).toBeUndefined();
    expect(asCompactionReason("pressure")).toBeUndefined();
  });

  test("an inherited Object property is not a reason", () => {
    // The check is an `in` against a map, so the prototype chain is reachable — and the
    // wire is a string the client does not control.
    expect(asCompactionReason("toString")).toBeUndefined();
    expect(asCompactionReason("constructor")).toBeUndefined();
  });
});
