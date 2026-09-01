import { describe, expect, test } from "bun:test";
import {
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
