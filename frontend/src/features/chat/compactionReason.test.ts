import { describe, expect, test } from "bun:test";
import {
  asCompactionReason,
  compactionReasonCause,
  compactionReasonSegment,
} from "./compactionReason";
import type { CompactionReason } from "./model";

const ALL: CompactionReason[] = ["threshold", "overflow", "manual"];

describe("every reason the wire can send has words", () => {
  // A missing entry renders `undefined` into the divider's label, which is worse than
  // saying nothing: the segment separator stays and the operator reads a fold with a
  // blank cause. Both maps are keyed by the union, so this is really a guard against
  // a *value* being added to the union with no wording behind it.
  test("both forms answer for all three", () => {
    for (const reason of ALL) {
      expect(compactionReasonSegment(reason)).toBeTruthy();
      expect(compactionReasonCause(reason)).toBeTruthy();
    }
  });

  test("no two reasons read the same", () => {
    // The whole point of carrying the reason is that a fold you asked for, a fold at
    // your threshold and a fold the provider forced are different events. Two of them
    // sharing a phrase would put that distinction back where it was.
    const segments = ALL.map(compactionReasonSegment);
    const causes = ALL.map(compactionReasonCause);
    expect(new Set(segments).size).toBe(ALL.length);
    expect(new Set(causes).size).toBe(ALL.length);
  });

  test("the clause completes 'Compacting because …' and the segment does not", () => {
    // The two forms are not interchangeable — the rail row splices its cause into a
    // sentence and the divider drops its segment into a `·`-joined label. A cause that
    // opened with a capital, or a segment that ended in a period, would read as broken
    // in the surface it lands in.
    for (const reason of ALL) {
      const cause = compactionReasonCause(reason);
      expect(cause[0]).toBe(cause[0].toLowerCase());
      expect(cause.endsWith(".")).toBe(false);
      expect(compactionReasonSegment(reason).endsWith(".")).toBe(false);
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
    // — omit the segment — because the divider reads correctly without it, where a raw
    // enum id on screen would not.
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
