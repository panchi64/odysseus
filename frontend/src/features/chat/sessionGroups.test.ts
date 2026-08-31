import { describe, expect, test } from "bun:test";
import { UNFILED_GROUP, groupSessions } from "./sessionGroups";
import type { ChatSummary } from "./model";

function session(id: string, extra: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id,
    title: id,
    updatedAt: "2026-08-30T00:00:00Z",
    messageCount: 2,
    mode: "code",
    ...extra,
  };
}

describe("groupSessions", () => {
  test("Normal and Research are one unheaded run", () => {
    // Their threads have no directory to be filed under, so a heading would name
    // nothing — the list is the list.
    for (const mode of ["normal", "research"] as const) {
      const rows = [session("a", { mode }), session("b", { mode })];
      const groups = groupSessions(rows, mode);
      expect(groups).toHaveLength(1);
      expect(groups[0].label).toBeNull();
      expect(groups[0].sessions).toEqual(rows);
    }
  });

  test("an empty list produces no groups at all", () => {
    // Not one empty section: the caller renders its own "no threads" state, and a
    // headerless empty run would draw nothing while still occupying a slot.
    expect(groupSessions([], "normal")).toEqual([]);
    expect(groupSessions([], "code")).toEqual([]);
  });

  test("Code groups by workspace", () => {
    const groups = groupSessions(
      [
        session("a", { workspace: "acme-api" }),
        session("b", { workspace: "odysseus" }),
        session("c", { workspace: "acme-api" }),
      ],
      "code",
    );
    expect(groups.map((g) => g.label)).toEqual(["acme-api", "odysseus"]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["a", "c"]);
    expect(groups[1].sessions.map((s) => s.id)).toEqual(["b"]);
  });

  test("groups appear in the order their first thread does", () => {
    // The input arrives pinned-first-then-newest, and that ordering has to carry
    // through: a pinned thread floats its whole workspace to the top. One rule,
    // visible in the rows, rather than a second sort the operator cannot see.
    const groups = groupSessions(
      [
        session("pinned", { workspace: "quiet-repo" }),
        session("recent", { workspace: "busy-repo" }),
        session("older", { workspace: "busy-repo" }),
      ],
      "code",
    );
    expect(groups.map((g) => g.label)).toEqual(["quiet-repo", "busy-repo"]);
  });

  test("a thread whose project is gone lands under Unfiled", () => {
    // Deleting a project unfiles its conversations rather than deleting them, so
    // this run is real and must stay reachable.
    const groups = groupSessions(
      [session("a"), session("b", { workspace: "acme-api" })],
      "code",
    );
    expect(groups.map((g) => g.label)).toEqual([UNFILED_GROUP, "acme-api"]);
  });

  test("an empty workspace string is treated as unfiled, not as a group", () => {
    // A blank heading would be a section the operator cannot identify.
    const groups = groupSessions([session("a", { workspace: "" })], "code");
    expect(groups.map((g) => g.label)).toEqual([UNFILED_GROUP]);
  });

  test("every thread survives the partition", () => {
    const rows = [
      session("a", { workspace: "one" }),
      session("b"),
      session("c", { workspace: "two" }),
      session("d", { workspace: "one" }),
    ];
    const flattened = groupSessions(rows, "code").flatMap((g) => g.sessions);
    expect(flattened).toHaveLength(rows.length);
    expect(new Set(flattened.map((s) => s.id)).size).toBe(rows.length);
  });
});
