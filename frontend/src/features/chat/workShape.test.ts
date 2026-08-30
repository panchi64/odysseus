import { describe, expect, test } from "bun:test";
import { SHAPE_MAX_ENTRIES, workShape } from "./workShape";
import { groupBlocks } from "./blocks";
import type { AssistantBlock, HostCommandPhase, ToolStatus } from "./model";

function tool(
  id: string,
  name: string,
  status: ToolStatus = "ok",
): AssistantBlock {
  return { kind: "tool", id, tool: { id, name, args: "", status } };
}

function think(id: string): AssistantBlock {
  return { kind: "thinking", id, text: "considering" };
}

function host(id: string, phase: HostCommandPhase): AssistantBlock {
  return {
    kind: "host_command",
    id,
    command: { toolCallId: id, command: "ls", phase },
  };
}

/** The shape of a set of blocks, as the caller sees it — through `groupBlocks`,
 *  the same way the work log builds the groups it hands over. */
function shape(blocks: AssistantBlock[]) {
  return workShape(groupBlocks(blocks));
}

describe("workShape names the tools, not the step count", () => {
  test("repeated calls to one tool collapse into a counted entry", () => {
    const s = shape([
      tool("a", "files_read_file"),
      tool("b", "files_read_file"),
      tool("c", "files_read_file"),
    ]);
    expect(s.entries).toEqual([
      { key: "files_read_file", icon: "file", label: "Read", count: 3 },
    ]);
  });

  test("entries keep the tool's own glyph and label, not its family's", () => {
    // `files_search_files` and `files_read_file` share the `files` category but
    // are different acts — the whole point of the registry table is that the
    // summary says "Search files" rather than bucketing both as "File".
    const s = shape([
      tool("a", "files_read_file"),
      tool("b", "files_search_files"),
    ]);
    expect(s.entries.map((e) => e.label)).toEqual(["Read", "Search files"]);
    expect(s.entries.map((e) => e.icon)).toEqual(["file", "search"]);
  });

  test("entries are in first-appearance order, not count order", () => {
    const s = shape([
      tool("a", "web_search"),
      tool("b", "files_read_file"),
      tool("c", "files_read_file"),
      tool("d", "files_read_file"),
    ]);
    expect(s.entries.map((e) => e.key)).toEqual([
      "web_search",
      "files_read_file",
    ]);
  });

  test("an unregistered tool still gets a family glyph and a humanized label", () => {
    // `external_*` connector tools are discovered per operator and can never be
    // enumerated in the table, so the summary must not depend on a table hit.
    const s = shape([tool("a", "external_linear_create_issue")]);
    expect(s.entries[0]).toEqual({
      key: "external_linear_create_issue",
      icon: "plug",
      label: "Linear create issue",
      count: 1,
    });
  });
});

describe("workShape reports failures separately from the entry cap", () => {
  test("failures are counted across the whole run", () => {
    const s = shape([
      tool("a", "files_read_file", "ok"),
      tool("b", "files_read_file", "error"),
      tool("c", "web_search", "error"),
    ]);
    expect(s.failed).toBe(2);
  });

  test("a failure past the entry cap is still reported", () => {
    // The cap drops SEGMENTS, never the failure count — otherwise a long run
    // could fold with its one failure invisible, which is the exact defect the
    // never-fold-a-failure rule exists to prevent.
    const blocks = [
      tool("a", "files_read_file"),
      tool("b", "web_search"),
      tool("c", "files_write_file"),
      tool("d", "shell_run_command"),
      tool("e", "memory_recall"),
      tool("f", "calendar_agenda", "error"),
    ];
    const s = shape(blocks);
    expect(s.entries).toHaveLength(SHAPE_MAX_ENTRIES);
    expect(s.overflow).toBe(2);
    expect(s.failed).toBe(1);
  });

  test("a failed host command counts as a failure", () => {
    const s = shape([host("a", "error")]);
    expect(s.failed).toBe(1);
  });

  test("a denied host command is a decision, not a failure", () => {
    expect(shape([host("a", "denied")]).failed).toBe(0);
  });
});

describe("workShape covers the work that is not a tool call", () => {
  test("every host command is one entry, borrowing the tool's registry glyph", () => {
    const s = shape([host("a", "ok"), host("b", "ok")]);
    expect(s.entries).toEqual([
      { key: "host", icon: "terminal", label: "Host command", count: 2 },
    ]);
  });

  test("reasoning is counted apart from the tool entries", () => {
    const s = shape([think("a"), tool("b", "web_search"), think("c")]);
    expect(s.thinks).toBe(2);
    expect(s.entries.map((e) => e.key)).toEqual(["web_search"]);
  });

  test("a run of nothing but View chips still summarizes as something", () => {
    const s = shape([
      { kind: "view_version", id: "a", snapshotId: "s1", title: "Report" },
      { kind: "view_version", id: "b", snapshotId: "s2", title: "Report" },
    ]);
    expect(s.entries).toEqual([
      { key: "view", icon: "panel-right", label: "View", count: 2 },
    ]);
  });

  test("an empty run is empty rather than undefined", () => {
    expect(shape([])).toEqual({
      entries: [],
      overflow: 0,
      failed: 0,
      thinks: 0,
    });
  });
});
