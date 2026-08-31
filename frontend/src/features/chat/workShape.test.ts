import { describe, expect, test } from "bun:test";
import { workShape } from "./workShape";
import { groupBlocks } from "./blocks";
import type { AssistantBlock, HostCommandPhase, ToolStatus } from "./model";

function tool(
  id: string,
  name: string,
  detail?: string,
  status: ToolStatus = "ok",
): AssistantBlock {
  return { kind: "tool", id, tool: { id, name, args: "", status, detail } };
}

function think(id: string): AssistantBlock {
  return { kind: "thinking", id, text: "considering" };
}

function host(id: string, phase: HostCommandPhase): AssistantBlock {
  return {
    kind: "host_command",
    id,
    command: {
      toolCallId: id,
      name: "shell_run_command",
      command: "ls -la",
      phase,
    },
  };
}

/** The shape of a set of blocks, as the caller sees it — through `groupBlocks`,
 *  the same way the work log builds the groups it hands over. */
function shape(blocks: AssistantBlock[]) {
  return workShape(groupBlocks(blocks));
}

describe("workShape reports the run's last step", () => {
  test("the latest call wins, not the first or the most frequent", () => {
    // Three reads then one search: a tally would have led with "Read ×3", which
    // is exactly the reading this replaced.
    const s = shape([
      tool("a", "files_read_file", "src/a.ts"),
      tool("b", "files_read_file", "src/b.ts"),
      tool("c", "files_read_file", "src/c.ts"),
      tool("d", "web_search", "pydantic ai streaming"),
    ]);
    expect(s.latest).toEqual({
      icon: "search",
      label: "Web search",
      detail: "pydantic ai streaming",
    });
  });

  test("the step keeps the tool's own glyph and label, not its family's", () => {
    // `files_search_files` and `files_read_file` share the `files` category but
    // are different acts — the registry table exists so the header says "Search
    // files" rather than bucketing both as "File".
    expect(shape([tool("a", "files_search_files")]).latest).toMatchObject({
      icon: "search",
      label: "Search files",
    });
    expect(shape([tool("a", "files_read_file")]).latest).toMatchObject({
      icon: "file",
      label: "Read",
    });
  });

  test("a call with no salient argument still names its kind", () => {
    // `detail` is undefined whenever `toolSummary` found nothing worth lifting.
    // The header must degrade to the bare verb rather than to nothing.
    const s = shape([tool("a", "memory_recall")]);
    expect(s.latest?.label).toBe("Recall");
    expect(s.latest?.detail).toBeUndefined();
  });

  test("an unregistered tool still gets a family glyph and a humanized label", () => {
    // `external_*` connector tools are discovered per operator and can never be
    // enumerated in the table, so the header must not depend on a table hit.
    expect(shape([tool("a", "external_linear_create_issue")]).latest).toEqual({
      icon: "plug",
      label: "Linear create issue",
      detail: undefined,
    });
  });

  test("reasoning is a step like any other when it is the last one", () => {
    const s = shape([tool("a", "web_search", "q"), think("b")]);
    expect(s.latest).toEqual({ icon: "cpu", label: "Reasoning" });
  });

  test("a host command reads as its command line", () => {
    expect(shape([host("a", "ok")]).latest).toEqual({
      icon: "terminal",
      label: "Host command",
      detail: "ls -la",
    });
  });

  test("a run of nothing but View chips still summarizes as something", () => {
    const s = shape([
      { kind: "view_version", id: "a", snapshotId: "s1", title: "Report" },
      { kind: "view_version", id: "b", snapshotId: "s2", title: "Chart" },
    ]);
    expect(s.latest).toEqual({
      icon: "panel-right",
      label: "View",
      detail: "Chart",
    });
  });
});

describe("a fold made only of injected context still names itself", () => {
  test("the header says which block, and that it was put there", () => {
    // A turn whose whole preamble folds must not summarize as nothing — and the word
    // "injected" is what keeps the fold's own header from reading like work the model
    // chose to do.
    const s = shape([
      {
        kind: "context",
        id: "c1",
        injection: {
          contributor: "skill_catalog",
          placement: "instructions",
          tokens: 900,
          text: "…",
          truncated: false,
        },
      },
    ]);
    expect(s.latest).toEqual({
      icon: "inject",
      label: "Skills",
      detail: "injected",
    });
  });
});

describe("a folded review names the call it judged", () => {
  function review(id: string, decision?: "allow" | "ask" | "block") {
    return {
      kind: "review" as const,
      id,
      review: {
        toolCallId: id,
        name: "shell_run_command",
        summary: "Runs the shell command: git status",
        decision,
      },
    };
  }

  test("the header borrows the judged tool's own glyph and word", () => {
    // "Review · Shell · review: allow" says what happened; a header reading
    // "Review" alone would say only that something did.
    expect(shape([review("r1", "allow")]).latest).toEqual({
      icon: "review",
      label: "Shell",
      detail: "review: allow",
    });
  });

  test("a review still in flight says so rather than reading as settled", () => {
    expect(shape([review("r1")]).latest?.detail).toBe("reviewing");
  });
});

describe("workShape reports how much is folded", () => {
  test("steps counts the rows expanding would reveal, one per group", () => {
    expect(shape([think("a"), tool("b", "web_search"), think("c")]).steps).toBe(
      3,
    );
  });

  test("batched host commands are one group and so one step", () => {
    // `groupBlocks` batches consecutive host commands into a single card, so
    // counting blocks here would promise two rows and open onto one.
    const s = shape([host("a", "ok"), host("b", "ok")]);
    expect(s.steps).toBe(1);
  });

  test("an empty run has no latest step and no size", () => {
    expect(shape([])).toEqual({ steps: 0 });
  });
});
