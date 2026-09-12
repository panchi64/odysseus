import { describe, expect, it } from "bun:test";
import { longTimestamp } from "./index";

/** Built from local-time parts on purpose. `longTimestamp` reads the operator's clock
 *  (see its docstring), so a fixture written as a UTC string would shift the expected
 *  output — and the assertions below — with the machine running the suite. */
function local(
  y: number,
  monthIndex: number,
  day: number,
  h = 12,
  min = 0,
): string {
  return new Date(y, monthIndex, day, h, min).toISOString();
}

describe("longTimestamp", () => {
  it("writes the stamp out in full", () => {
    expect(longTimestamp(local(2026, 8, 10, 21, 3))).toBe(
      "Thu, Sept 10th 2026 @ 9:03PM",
    );
  });

  it("spells the months the way the product writes them", () => {
    // `Intl`'s `short` gives `Sep`/`Jun`/`Jul`; these three are the ones that differ.
    expect(longTimestamp(local(2026, 5, 1))).toContain("June");
    expect(longTimestamp(local(2026, 6, 1))).toContain("July");
    expect(longTimestamp(local(2026, 8, 1))).toContain("Sept");
    expect(longTimestamp(local(2026, 0, 1))).toContain("Jan");
  });

  it("takes th for the teens and the matching suffix elsewhere", () => {
    const day = (n: number) => longTimestamp(local(2026, 0, n)).split(" ")[2];
    expect(day(1)).toBe("1st");
    expect(day(2)).toBe("2nd");
    expect(day(3)).toBe("3rd");
    expect(day(4)).toBe("4th");
    // The teens are the case the naive mod-10 rule gets wrong.
    expect(day(11)).toBe("11th");
    expect(day(12)).toBe("12th");
    expect(day(13)).toBe("13th");
    expect(day(21)).toBe("21st");
    expect(day(22)).toBe("22nd");
    expect(day(23)).toBe("23rd");
    expect(day(31)).toBe("31st");
  });

  it("puts midnight and noon on 12, not 0", () => {
    expect(longTimestamp(local(2026, 0, 1, 0, 5))).toContain("12:05AM");
    expect(longTimestamp(local(2026, 0, 1, 12, 5))).toContain("12:05PM");
    expect(longTimestamp(local(2026, 0, 1, 23, 59))).toContain("11:59PM");
    expect(longTimestamp(local(2026, 0, 1, 1, 0))).toContain("1:00AM");
  });

  it("zero-pads the minute so the column stays aligned", () => {
    expect(longTimestamp(local(2026, 0, 1, 9, 3))).toContain("9:03AM");
  });

  it("hands back unparseable input rather than NaN", () => {
    // Matching `timestamp`/`date`/`relativeTime` beside it: a bad stamp shows the raw
    // value, which is at least diagnosable, instead of "Invalid Date".
    expect(longTimestamp("not a date")).toBe("not a date");
    expect(longTimestamp("")).toBe("");
  });
});
