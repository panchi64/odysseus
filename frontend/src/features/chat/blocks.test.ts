import { describe, expect, test } from "bun:test";
import {
  WORK_LOG_MIN_RUN,
  layoutItemKey,
  liveToolGroupIds,
  groupBlocks,
  planTurnLayout,
  runningTools,
} from "./blocks";
import type {
  AssistantBlock,
  HostCommandPhase,
  ToolImage,
  ToolStatus,
} from "./model";

/** A tool block, named so an assertion can point at it by name. */
function tool(id: string, name: string, status: ToolStatus): AssistantBlock {
  return { kind: "tool", id, tool: { id, name, args: "", status } };
}

/** A settled tool call that came back with a screenshot — or, given an empty list, one
 *  that reported no pictures at all. */
function shot(
  id: string,
  images: ToolImage[] = [{ mediaType: "image/png", data: "QUJD" }],
): AssistantBlock {
  return {
    kind: "tool",
    id,
    tool: { id, name: "browse_screenshot", args: "", status: "ok", images },
  };
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

describe("a call that came back with a picture keeps its run inline", () => {
  // The defect this covers bites hardest in the case that produces the pictures: an
  // agent that screenshots repeatedly makes a *run* of settled calls, which is exactly
  // what folds — so the images would be hidden precisely when there are the most of
  // them to see. Same fixture discipline as the failure rule: mid-run, settled turn,
  // enough collapsible groups either side that dropping the guard really does fold.
  test("a settled turn with a screenshot does not fold", () => {
    expect(
      plan(
        [
          tool("a", "browse_click", "ok"),
          shot("b"),
          tool("c", "browse_get_text", "ok"),
          tool("d", "browse_click", "ok"),
        ],
        false,
      ),
    ).toEqual(["a", "b", "c", "d"]);
  });

  test("an empty image list is not a picture", () => {
    // The rule reads `images?.length`, not `images !== undefined` — a call that
    // reported an empty list has nothing to show and must fold like any other.
    expect(
      plan(
        [
          tool("a", "browse_click", "ok"),
          shot("b", []),
          tool("c", "browse_click", "ok"),
        ],
        false,
      ),
    ).toEqual(["worklog"]);
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

describe("injected context recedes into the fold", () => {
  /** One block the chassis put in front of the model. */
  function injected(id: string, contributor: string): AssistantBlock {
    return {
      kind: "context",
      id,
      injection: {
        contributor,
        placement: "instructions",
        tokens: 120,
        text: "…",
        truncated: false,
      },
    };
  }

  test("a turn's preamble folds instead of leading with itself", () => {
    // Every turn opens with a clump of these. Left inline they would push the answer
    // down the page behind three rows of frame — and unlike a tool call there is
    // nothing in them to watch, act on, or wait for.
    expect(
      plan(
        [
          injected("c1", "repo"),
          injected("c2", "skill_catalog"),
          injected("c3", "date"),
          text("t"),
        ],
        false,
      ),
    ).toEqual(["worklog", "t"]);
  });

  test("it counts toward a fold the work alone would not reach", () => {
    // Two settled calls stay inline on their own (below WORK_LOG_MIN_RUN); with the
    // turn's own preamble ahead of them the run is long enough to fold, which is the
    // honest reading — the operator has three-plus rows of process either way.
    expect(WORK_LOG_MIN_RUN).toBe(3);
    expect(
      plan(
        [
          injected("c1", "repo"),
          tool("a", "files_read_file", "ok"),
          tool("b", "web_search", "ok"),
          text("t"),
        ],
        false,
      ),
    ).toEqual(["worklog", "t"]);
  });

  test("a live call still breaks the fold open around it", () => {
    // The pin rules are about the *work*, and an injection must not smother them: a
    // call still in flight stays on screen with its spinner whatever sits beside it.
    expect(
      plan([injected("c1", "repo"), tool("a", "web_search", "running")], false),
    ).toEqual(["c1", "a"]);
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

describe("a review folds with the work, unless it refused something", () => {
  /** One call the chassis ruled on in the operator's place. */
  function review(
    id: string,
    decision?: "allow" | "ask" | "block",
  ): AssistantBlock {
    return {
      kind: "review",
      id,
      review: {
        toolCallId: id,
        name: "shell_run_command",
        summary: "Runs the shell command: git status",
        decision,
        stage: "judge",
        reason: "reads the workspace and changes nothing",
      },
    };
  }

  test("a cleared call's review recedes like the work it cleared", () => {
    // Nothing about it needs the operator *now*: the call it cleared ran, and the
    // account of why is one fold away.
    expect(
      plan(
        [
          review("r1", "allow"),
          tool("a", "shell_run_command", "ok"),
          tool("b", "files_read_file", "ok"),
          text("t"),
        ],
        false,
      ),
    ).toEqual(["worklog", "t"]);
  });

  test("a refusal stays on screen however much settles around it", () => {
    // The single thing in a turn the operator is most likely to disagree with, and the
    // only one with no following row to account for it — a refused call is followed by
    // nothing at all. Burying it would make Auto's promise unverifiable in practice.
    expect(
      plan(
        [
          tool("a", "files_read_file", "ok"),
          tool("b", "files_read_file", "ok"),
          tool("c", "files_read_file", "ok"),
          review("r1", "block"),
          tool("d", "files_read_file", "ok"),
          tool("e", "files_read_file", "ok"),
          tool("f", "files_read_file", "ok"),
          text("t"),
        ],
        false,
      ),
    ).toEqual(["worklog", "r1", "worklog", "t"]);
  });

  test("a review still in flight folds rather than pinning the turn open", () => {
    // It resolves on its own in a second or two, and a row that pins the log open for
    // every reviewed call would leave an Auto thread permanently unfolded.
    expect(
      plan(
        [
          review("r1"),
          tool("a", "files_read_file", "ok"),
          tool("b", "files_read_file", "ok"),
          text("t"),
        ],
        false,
      ),
    ).toEqual(["worklog", "t"]);
  });
});
