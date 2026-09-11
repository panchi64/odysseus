/** The registry's own invariants.
 *
 *  Most of what could go wrong here is already a compile error — `SurfaceId` is derived
 *  from the array, so a surface without a renderer or without a source will not build.
 *  What the type system cannot see is whether the *data* is coherent: two rows claiming
 *  one id, a panel whose resting width is under its own minimum, a strip that would grow
 *  without bound. Each of those renders perfectly and behaves wrongly.
 */

import { describe, expect, test } from "bun:test";
import {
  isPanelSpec,
  isStripSpec,
  orderOf,
  shapeOf,
  SURFACE_BY_ID,
  SURFACE_IDS,
  SURFACES,
  surfaceSpec,
} from "./surfaces";

describe("the registry is coherent", () => {
  test("ids are unique", () => {
    expect(new Set(SURFACE_IDS).size).toBe(SURFACE_IDS.length);
  });

  test("every id resolves to its own spec", () => {
    for (const id of SURFACE_IDS) expect(surfaceSpec(id).id).toBe(id);
    expect(Object.keys(SURFACE_BY_ID).length).toBe(SURFACES.length);
  });

  test("order follows declaration, which is also how strips stack", () => {
    expect(SURFACE_IDS.map(orderOf)).toEqual(SURFACE_IDS.map((_, i) => i));
  });

  test("every surface is one shape or the other, and the helpers agree", () => {
    for (const spec of SURFACES) {
      expect(isPanelSpec(spec) !== isStripSpec(spec)).toBe(true);
      expect(shapeOf(spec.id)).toBe(spec.shape);
    }
  });

  test("every label is distinct, since the header names buttons by it", () => {
    const labels = SURFACES.map((s) => s.label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("the numbers are usable", () => {
  test("a panel's resting width is at least its minimum", () => {
    for (const spec of SURFACES) {
      if (!isPanelSpec(spec)) continue;
      expect(spec.defaultWidth).toBeGreaterThanOrEqual(spec.minWidth);
    }
  });

  test("a panel's minimums are positive — a zero would make anything 'fit'", () => {
    for (const spec of SURFACES) {
      if (!isPanelSpec(spec)) continue;
      expect(spec.minWidth).toBeGreaterThan(0);
      expect(spec.minHeight).toBeGreaterThan(0);
    }
  });

  test("a strip is capped, or it is a panel wearing a strip's clothes", () => {
    for (const spec of SURFACES) {
      if (!isStripSpec(spec)) continue;
      expect(spec.maxRows).toBeGreaterThan(0);
      expect(spec.maxRows).toBeLessThanOrEqual(12);
    }
  });
});
