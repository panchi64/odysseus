import { describe, expect, test } from "bun:test";
import type { ContextSegment } from "~/lib/stream";
import type { ContextUsage } from "../model";
import { contextRows, segmentLabel } from "./contextRows";

const segment = (
  id: string,
  group: ContextSegment["group"],
  tokens: number,
  count: number | null = null,
): ContextSegment => ({ id, group, tokens, count });

const usage = (
  over: Partial<ContextUsage> & Pick<ContextUsage, "used" | "window">,
): ContextUsage => ({
  fraction: over.used / over.window,
  level: "nominal",
  parts: null,
  ...over,
});

describe("the rows are the backend's figures, laid out", () => {
  test("every row is a share of the window, and they total it", () => {
    // The bar *is* the window: a row measured against `used` would draw a full strip
    // on a 5%-full thread, contradicting the ring beside it.
    const rows = contextRows(
      usage({
        used: 25_000,
        window: 100_000,
        parts: {
          system: 5_000,
          tools: 10_000,
          messages: 10_000,
          segments: [],
        },
      }),
    );
    expect(rows.map((r) => r.share)).toEqual([5, 10, 10, 75]);
    expect(rows.reduce((sum, r) => sum + r.share, 0)).toBe(100);
  });

  test("free space is always the last row, and is what is left", () => {
    const rows = contextRows(usage({ used: 40_000, window: 100_000 }));
    const free = rows.at(-1)!;
    expect(free.key).toBe("free");
    expect(free.tokens).toBe(60_000);
  });

  test("a group with no weight is left out rather than shown as a zero", () => {
    // A thread that has run with no tools switched on genuinely has no tool row. A
    // zero would read as a measurement of nothing rather than nothing measured.
    const rows = contextRows(
      usage({
        used: 9_000,
        window: 100_000,
        parts: { system: 4_000, tools: 0, messages: 5_000, segments: [] },
      }),
    );
    expect(rows.map((r) => r.key)).toEqual(["system", "messages", "free"]);
  });

  test("detail lands under its own group, heaviest first", () => {
    const rows = contextRows(
      usage({
        used: 30_000,
        window: 100_000,
        parts: {
          system: 5_000,
          tools: 15_000,
          messages: 10_000,
          segments: [
            segment("files", "tools", 4_000, 8),
            segment("external", "tools", 11_000, 68),
            segment("base", "brief", 5_000),
            segment("tool_results", "messages", 10_000),
          ],
        },
      }),
    );
    const tools = rows.find((r) => r.key === "tools")!;
    expect(tools.detail.map((d) => d.key)).toEqual(["external", "files"]);
    expect(tools.detail[0]!.count).toBe(68);
    expect(rows.find((r) => r.key === "system")!.detail).toHaveLength(1);
  });

  test("a group the backend didn't itemise carries no detail to expand", () => {
    // The coarse reading never depends on the fine one — an overhead measured before
    // the itemisation existed still draws its bar.
    const rows = contextRows(
      usage({
        used: 10_000,
        window: 100_000,
        parts: { system: 2_000, tools: 3_000, messages: 5_000, segments: [] },
      }),
    );
    expect(rows.every((r) => r.detail.length === 0)).toBe(true);
  });

  test("with no split measured, the window still reads as full as it is", () => {
    const rows = contextRows(usage({ used: 20_000, window: 100_000 }));
    expect(rows.map((r) => r.key)).toEqual(["used", "free"]);
    expect(rows[0]!.share).toBe(20);
  });

  test("a window the backend reports as full leaves no negative remainder", () => {
    const rows = contextRows(usage({ used: 120_000, window: 100_000 }));
    expect(rows.at(-1)!.tokens).toBe(0);
    expect(rows.at(-1)!.share).toBe(0);
  });
});

describe("a slug becomes a label without a registry to maintain", () => {
  test("an unknown id reads as its own words", () => {
    // Every tool category and instruction provider the backend grows later has to
    // render correctly with no edit here — otherwise this list becomes a second
    // catalog to keep in step with the real one.
    expect(segmentLabel("skill_catalog")).toBe("Skill catalog");
    expect(segmentLabel("files")).toBe("Files");
    expect(segmentLabel("tool_results")).toBe("Tool results");
  });

  test("the few slugs whose own words would mislead are named", () => {
    expect(segmentLabel("base")).toBe("Base prompt");
    expect(segmentLabel("external")).toBe("MCP & connectors");
  });
});
