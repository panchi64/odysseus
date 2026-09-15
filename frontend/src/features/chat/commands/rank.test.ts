import { describe, expect, test } from "bun:test";
import { groupCommands, invocationName, rankCommands } from "./rank";
import type { Command, CommandGroup } from "./model";

function cmd(over: Partial<Command> & { name: string }): Command {
  return {
    qualifiedName: `agent:${over.name}`,
    group: "agent",
    title: over.name,
    description: "",
    argumentHint: null,
    kind: "prompt",
    actionId: null,
    actionArgument: null,
    shadowedBy: null,
    ...over,
  };
}

/** Ordered to **fight** the ranking: `review` is a name-prefix on the third row, a
 *  name-substring on the second, and only a description match on the first — so
 *  declaration order gives the wrong answer for every bucket. */
const ROWS: Command[] = [
  cmd({
    name: "compact",
    description: "fold this thread before you review it",
  }),
  cmd({ name: "pre-review", title: "Pre-review" }),
  cmd({ name: "reviewer", title: "Reviewer" }),
  cmd({ name: "worker", title: "Review-free worker" }),
];

describe("rankCommands", () => {
  test("a name prefix beats a name substring", () => {
    const names = rankCommands("review", ROWS).map((c) => c.name);
    expect(names.indexOf("reviewer")).toBeLessThan(names.indexOf("pre-review"));
  });

  test("a name substring beats a title match", () => {
    const names = rankCommands("review", ROWS).map((c) => c.name);
    expect(names.indexOf("pre-review")).toBeLessThan(names.indexOf("worker"));
  });

  test("a title match beats a description-only match", () => {
    const names = rankCommands("review", ROWS).map((c) => c.name);
    expect(names.indexOf("worker")).toBeLessThan(names.indexOf("compact"));
  });

  test("a command is counted once, by its strongest field", () => {
    // `reviewer` matches on name AND title; it must not appear twice.
    expect(
      rankCommands("review", ROWS).filter((c) => c.name === "reviewer"),
    ).toHaveLength(1);
  });

  test("an empty query is the whole catalog, in declared order", () => {
    // The menu opens on the bare trigger, so it doubles as a directory of what exists.
    expect(rankCommands("", ROWS)).toEqual(ROWS);
    expect(rankCommands("   ", ROWS)).toEqual(ROWS);
  });

  test("matching is case-insensitive", () => {
    expect(rankCommands("REVIEWER", ROWS)[0]!.name).toBe("reviewer");
  });

  test("no match is an empty list, not the catalog", () => {
    expect(rankCommands("zzz", ROWS)).toEqual([]);
  });
});

describe("groupCommands", () => {
  // Declared out of order, so a group list that merely preserved input order would
  // give the same answer as one that sorts — and would be wrong.
  const GROUPS: CommandGroup[] = [
    { id: "agent", label: "Sub-agents", order: 2 },
    { id: "action", label: "This thread", order: 0 },
  ];
  const ROWS_BY_GROUP: Command[] = [
    cmd({ name: "reviewer", group: "agent" }),
    cmd({ name: "compact", group: "action" }),
  ];

  test("headings follow the backend's declared order, not the ranking", () => {
    // A heading that jumps around as the operator types is harder to read than a
    // stable one; ranking decides the rows, not the sections.
    expect(groupCommands(ROWS_BY_GROUP, GROUPS).map((g) => g.id)).toEqual([
      "action",
      "agent",
    ]);
  });

  test("a group with nothing left in it is dropped", () => {
    const only = ROWS_BY_GROUP.filter((c) => c.group === "action");
    expect(groupCommands(only, GROUPS).map((g) => g.id)).toEqual(["action"]);
  });

  test("a row whose group is not declared is left out rather than orphaned", () => {
    const stray = [cmd({ name: "x", group: "workflow" })];
    expect(groupCommands(stray, GROUPS)).toEqual([]);
  });
});

describe("invocationName", () => {
  test("an unshadowed command goes by its bare name", () => {
    expect(invocationName(cmd({ name: "reviewer" }))).toBe("reviewer");
  });

  test("a shadowed command goes by its qualified name", () => {
    // Otherwise picking the row that was *shown* would run the one that won the name.
    const shadowed = cmd({ name: "reviewer", shadowedBy: "skill:reviewer" });
    expect(invocationName(shadowed)).toBe("agent:reviewer");
  });
});
