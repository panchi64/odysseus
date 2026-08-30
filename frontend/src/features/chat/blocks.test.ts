import { describe, expect, test } from "bun:test";
import {
  WORK_LOG_MIN_RUN,
  layoutItemKey,
  liveToolGroupIds,
  groupBlocks,
  planTurnLayout,
  runningTools,
} from "./blocks";
import type { AssistantBlock, HostCommandPhase, ToolStatus } from "./model";

/** A tool block, named so an assertion can point at it by name. */
function tool(id: string, name: string, status: ToolStatus): AssistantBlock {
  return { kind: "tool", id, tool: { id, name, args: "", status } };
}

function text(id: string): AssistantBlock {
  return { kind: "text", id, text: "done" };
}

function host(id: string, phase: HostCommandPhase): AssistantBlock {
  return {
    kind: "host_command",
    id,
    command: { toolCallId: id, command: "ls", phase },
  };
}

/** The layout of a turn, as the kinds it puts on the rail — "worklog" for a fold,
 *  the group's own id for anything left inline. Defaults to a streaming turn;
 *  pass `false` for a settled one, which is the harder case for any rule that
 *  keeps something visible — `planTurnLayout`'s own tail guard only runs while
 *  streaming, so a settled turn has nothing else propping the block up. */
function plan(blocks: AssistantBlock[], streaming = true): string[] {
  return planTurnLayout(groupBlocks(blocks), { streaming }).map((item) =>
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
    // The counterpart: a cleanly finished batch must still recede into the work
    // log. (Every call here is `ok` on purpose — a failure among them would be
    // pinned inline by its own rule, which is the next describe block.)
    expect(
      plan([
        tool("a", "web_search", "ok"),
        tool("b", "web_search", "ok"),
        tool("c", "web_search", "ok"),
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

describe("a failed call keeps its run inline", () => {
  // The defect these cover: the card auto-expands on error, but the work log
  // folded shut around it — so the one event that should interrupt was the one
  // event buried, and a swallowed tool failure is how a contaminated answer gets
  // trusted. Each fixture puts the failure MID-RUN with enough collapsible
  // groups around it that dropping the guard really does fold over it.
  test("a settled turn with a failure does not fold", () => {
    // The case that matters most: nothing is streaming, so `planTurnLayout`'s
    // trailing-group guard is not running and only the failure rule is holding
    // this open.
    expect(
      plan(
        [
          tool("a", "web_search", "ok"),
          tool("b", "files_read_file", "error"),
          tool("c", "web_search", "ok"),
          tool("d", "web_search", "ok"),
        ],
        false,
      ),
    ).toEqual(["a", "b", "c", "d"]);
  });

  test("a failure mid-stream does not fold", () => {
    expect(
      plan([
        tool("a", "web_search", "ok"),
        tool("b", "files_read_file", "error"),
        tool("c", "web_search", "ok"),
        text("t"),
      ]),
    ).toEqual(["a", "b", "c", "t"]);
  });

  test("a settled turn with no failure still folds", () => {
    // The counterpart that proves the rule is doing the work above, rather than
    // settled turns simply never folding.
    expect(
      plan(
        [
          tool("a", "web_search", "ok"),
          tool("b", "files_read_file", "ok"),
          tool("c", "web_search", "ok"),
          tool("d", "web_search", "ok"),
        ],
        false,
      ),
    ).toEqual(["worklog"]);
  });

  test("a failed host command keeps its run inline", () => {
    expect(
      plan(
        [
          tool("a", "web_search", "ok"),
          host("b", "error"),
          tool("c", "web_search", "ok"),
          tool("d", "web_search", "ok"),
        ],
        false,
      ),
    ).toEqual(["a", "b", "c", "d"]);
  });

  test("a denied host command is a decision, not a failure, and folds", () => {
    // The operator already dealt with this one; keeping it pinned forever would
    // mean every refusal permanently un-folds the turn it happened in.
    expect(
      plan(
        [
          tool("a", "web_search", "ok"),
          host("b", "denied"),
          tool("c", "web_search", "ok"),
          tool("d", "web_search", "ok"),
        ],
        false,
      ),
    ).toEqual(["worklog"]);
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
