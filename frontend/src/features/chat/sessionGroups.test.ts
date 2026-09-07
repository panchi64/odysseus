import { describe, expect, test } from "bun:test";
import {
  UNFILED_GROUP,
  groupSessions,
  type WorkspaceDirectory,
} from "./sessionGroups";
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

function dir(id: string, label = id): WorkspaceDirectory {
  return { id, label };
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

  test("Code groups by project", () => {
    const groups = groupSessions(
      [
        session("a", { projectId: "p1" }),
        session("b", { projectId: "p2" }),
        session("c", { projectId: "p1" }),
      ],
      "code",
      [dir("p1", "acme-api"), dir("p2", "odysseus")],
    );
    expect(groups.map((g) => g.label)).toEqual(["acme-api", "odysseus"]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["a", "c"]);
    expect(groups[1].sessions.map((s) => s.id)).toEqual(["b"]);
  });

  test("two directories sharing a basename stay two groups", () => {
    // The whole reason filing is by project id. Two repositories both holding a
    // `frontend` are two places to work, and merging them would point one section's
    // controls at whichever won.
    const groups = groupSessions(
      [session("a", { projectId: "p1" }), session("b", { projectId: "p2" })],
      "code",
      [dir("p1", "acme/frontend"), dir("p2", "beta/frontend")],
    );
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.projectId)).toEqual(["p1", "p2"]);
  });

  test("a directory with no threads still gets a section", () => {
    // The directory comes first now — it is where a code thread is started from, so
    // an empty one is the ordinary beginning of a piece of work, not a dead row.
    const groups = groupSessions([], "code", [dir("p1", "acme-api")]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("acme-api");
    expect(groups[0].sessions).toEqual([]);
  });

  test("empty directories trail the ones holding threads", () => {
    // A section with nothing in it has nothing to say about how recently the operator
    // was there, so it cannot claim a place among the sections that do.
    const groups = groupSessions(
      [session("a", { projectId: "p2" })],
      "code",
      // Listing order deliberately puts the empty one first — the rule has to beat it.
      [dir("p1", "empty"), dir("p2", "worked-in")],
    );
    expect(groups.map((g) => g.label)).toEqual(["worked-in", "empty"]);
  });

  test("groups holding threads appear in the order their first thread does", () => {
    // The input arrives pinned-first-then-newest, and that ordering has to carry
    // through: a pinned thread floats its whole workspace to the top. One rule,
    // visible in the rows, rather than a second sort the operator cannot see.
    const groups = groupSessions(
      [
        session("pinned", { projectId: "p1" }),
        session("recent", { projectId: "p2" }),
        session("older", { projectId: "p2" }),
      ],
      "code",
      // Listing order is the opposite, so declaration order cannot be what passes this.
      [dir("p2", "busy-repo"), dir("p1", "quiet-repo")],
    );
    expect(groups.map((g) => g.label)).toEqual(["quiet-repo", "busy-repo"]);
  });

  test("a thread whose project is gone lands under Unfiled", () => {
    // Deleting a project unfiles its conversations rather than deleting them, so
    // this run is real and must stay reachable.
    const groups = groupSessions(
      [session("a"), session("b", { projectId: "p1" })],
      "code",
      [dir("p1", "acme-api")],
    );
    expect(groups.map((g) => g.label)).toEqual([UNFILED_GROUP, "acme-api"]);
    expect(groups[0].projectId).toBeNull();
    expect(groups[1].projectId).toBe("p1");
  });

  test("a thread whose directory is not listed is left out, not unfiled", () => {
    // The archived case. Archiving is the operator saying they no longer work there;
    // sweeping the directory's threads loose into Unfiled would honour the letter of
    // that and none of the intent. Nothing is lost — un-archiving brings both back.
    const groups = groupSessions(
      [session("archived", { projectId: "gone" }), session("kept")],
      "code",
      [],
    );
    expect(groups.map((g) => g.label)).toEqual([UNFILED_GROUP]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["kept"]);
  });

  test("Unfiled carries a null projectId, and a directory carries its own", () => {
    // What the rail's staged-highlight compares against. If `Unfiled` reported a
    // projectId of its own it would be offered controls it cannot honour, and callers
    // comparing against "nothing staged" must be able to tell the two nulls apart.
    const groups = groupSessions(
      [session("a"), session("b", { projectId: "p1" })],
      "code",
      [dir("p1")],
    );
    expect(groups.map((g) => g.projectId)).toEqual([null, "p1"]);
  });

  test("every listed thread survives the partition", () => {
    const rows = [
      session("a", { projectId: "p1" }),
      session("b"),
      session("c", { projectId: "p2" }),
      session("d", { projectId: "p1" }),
    ];
    const flattened = groupSessions(rows, "code", [
      dir("p1"),
      dir("p2"),
    ]).flatMap((g) => g.sessions);
    expect(flattened).toHaveLength(rows.length);
    expect(new Set(flattened.map((s) => s.id)).size).toBe(rows.length);
  });
});
