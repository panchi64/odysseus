import { describe, expect, test } from "bun:test";
import {
  WORK_LOG_MIN_RUN,
  layoutItemKey,
  liveToolGroupIds,
  groupBlocks,
  planTurnLayout,
  runningTools,
} from "./blocks";
import type { AssistantBlock, ToolStatus } from "./model";

/** A tool block, named so an assertion can point at it by name. */
function tool(id: string, name: string, status: ToolStatus): AssistantBlock {
  return { kind: "tool", id, tool: { id, name, args: "", status } };
}

function text(id: string): AssistantBlock {
  return { kind: "text", id, text: "done" };
}

/** The layout of a streaming turn, as the kinds it puts on the rail — "worklog"
 *  for a fold, the group's own id for anything left inline. */
function plan(blocks: AssistantBlock[]): string[] {
  return planTurnLayout(groupBlocks(blocks), { streaming: true }).map((item) =>
    item.type === "worklog" ? "worklog" : item.group.id,
  );
}

describe("parallel tool calls stay visible while they run", () => {
  // These fixtures FIGHT the rule: `planTurnLayout` already keeps the trailing group
  // inline while streaming, so a running call in last position would pass with the
  // guard deleted. Each one puts it mid-run instead, with enough collapsible groups
  // around it that dropping the guard really does fold a work log over it.
  test("a batch with one call still running does not fold", () => {
    expect(WORK_LOG_MIN_RUN).toBe(3);
    // Guard removed: a, b, c fold and only the tail d stays inline.
    expect(
      plan([
        tool("a", "web_search", "ok"),
        tool("b", "web_search", "running"),
        tool("c", "web_search", "ok"),
        tool("d", "web_search", "ok"),
      ]),
    ).toEqual(["a", "b", "c", "d"]);
  });

  test("a whole batch still running stays inline", () => {
    // The trailing block is the answer, so no tool here is protected by position.
    expect(
      plan([
        tool("a", "web_search", "running"),
        tool("b", "web_search", "running"),
        tool("c", "web_search", "running"),
        tool("d", "web_search", "running"),
        text("t"),
      ]),
    ).toEqual(["a", "b", "c", "d", "t"]);
  });

  test("the same batch, all settled, folds as before", () => {
    // The counterpart: a finished batch must still recede into the work log.
    expect(
      plan([
        tool("a", "web_search", "ok"),
        tool("b", "web_search", "ok"),
        tool("c", "web_search", "error"),
        text("t"),
      ]),
    ).toEqual(["worklog", "t"]);
  });

  test("a settled batch's fold keys on where it starts", () => {
    const items = planTurnLayout(
      groupBlocks([
        tool("a", "web_search", "ok"),
        tool("b", "web_search", "ok"),
        tool("c", "web_search", "ok"),
        text("t"),
      ]),
      { streaming: true },
    );
    expect(layoutItemKey(items[0])).toBe("w:a");
  });
});

describe("liveToolGroupIds", () => {
  test("names every group with a call in flight, not just the last", () => {
    const groups = groupBlocks([
      tool("a", "web_search", "running"),
      tool("b", "web_fetch", "ok"),
      tool("c", "code_execute", "running"),
    ]);
    expect(liveToolGroupIds(groups)).toEqual(new Set(["a", "c"]));
  });

  test("is empty once the batch settles", () => {
    const groups = groupBlocks([
      tool("a", "web_search", "ok"),
      tool("b", "web_fetch", "error"),
    ]);
    expect(liveToolGroupIds(groups).size).toBe(0);
  });
});

describe("runningTools", () => {
  test("collects in-flight calls across the turn, in order", () => {
    // The running call is first and the trailing block isn't one — the case a tail-only
    // read gets wrong.
    expect(
      runningTools([
        tool("a", "web_search", "running"),
        tool("b", "web_fetch", "ok"),
        text("t"),
      ]).map((t) => t.name),
    ).toEqual(["web_search"]);
  });

  test("returns the whole batch when several are out", () => {
    expect(
      runningTools([
        tool("a", "web_search", "running"),
        tool("b", "web_fetch", "running"),
      ]),
    ).toHaveLength(2);
  });

  test("is empty for a turn with no tools", () => {
    expect(runningTools([text("t")])).toEqual([]);
    expect(runningTools(undefined)).toEqual([]);
  });
});
