import { describe, expect, test } from "bun:test";
import { inertBand } from "./contextBands";

const defaults = { foldEnabled: true, foldThreshold: 0.8, alert: 0.9 };

describe("inertBand", () => {
  test("the shipped defaults leave the red band unreachable, and say so", () => {
    // 75 / 80 / 90: the fold empties the window before 90 can ever be reached. This is
    // the arrangement every install starts in, which is precisely why it is worth a line
    // rather than being treated as an exotic misconfiguration.
    expect(inertBand(defaults)).toEqual({ at: 90, fold: 80 });
  });

  test("folding switched off makes the band reachable again", () => {
    // Not a special case — it is the state the bands were written for.
    expect(inertBand({ ...defaults, foldEnabled: false })).toBeNull();
  });

  test("a band below the fold is coherent and says nothing", () => {
    expect(inertBand({ ...defaults, alert: 0.7 })).toBeNull();
  });

  test("a band level with the fold still lights on the turn that reaches it", () => {
    expect(inertBand({ ...defaults, alert: 0.8 })).toBeNull();
  });

  test("a difference too small to show on screen is not reported", () => {
    // Both round to 80: telling the operator their 80% band is unreachable because the
    // fold is at 80% would be a line about a distinction the screen cannot draw.
    expect(inertBand({ ...defaults, alert: 0.804 })).toBeNull();
  });

  test("a fold at the very top leaves nothing inert", () => {
    expect(
      inertBand({ foldEnabled: true, foldThreshold: 1, alert: 1 }),
    ).toBeNull();
  });
});
