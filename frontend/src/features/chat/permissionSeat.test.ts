import { describe, expect, test } from "bun:test";
import { DEFAULT_PERMISSION_LEVEL } from "./model";
import { seatPermission } from "./permissionSeat";

describe("a thread's level never rides another thread's send", () => {
  test("opening a different thread drops the level before its history lands", () => {
    // The bug this rule exists for: sitting in thread A at auto, click thread B, send
    // before the fetch answers. The level in hand is A's, the id on the wire is B's,
    // and the backend persists what it is sent — so B, which the operator had set to
    // plan, comes back auto-approving with nothing on screen having said so.
    expect(
      seatPermission({ currentId: "B", owner: "A", stored: undefined }),
    ).toEqual({ owner: "B", level: DEFAULT_PERMISSION_LEVEL });
  });

  test("the same window opening from a staged composer", () => {
    // Same window, reached the other way: a level chosen on the unsaved composer is
    // owned by no thread, and must not follow the operator into one.
    expect(
      seatPermission({ currentId: "B", owner: null, stored: undefined }),
    ).toEqual({ owner: "B", level: DEFAULT_PERMISSION_LEVEL });
  });

  test("the loaded thread's own level wins once it arrives", () => {
    expect(
      seatPermission({ currentId: "B", owner: "B", stored: "plan" }),
    ).toEqual({ owner: "B", level: "plan" });
  });

  test("starting a new thread returns to the default", () => {
    expect(
      seatPermission({ currentId: null, owner: "A", stored: undefined }),
    ).toEqual({ owner: null, level: DEFAULT_PERMISSION_LEVEL });
  });
});

describe("a level the operator chose for the thread on screen is left alone", () => {
  test("nothing to re-seat while the same thread is open", () => {
    // No answer at all, rather than an answer that happens to match: re-seating on
    // every pass would snap a mid-thread choice back the moment anything else in the
    // effect's dependencies moved.
    expect(
      seatPermission({ currentId: "B", owner: "B", stored: undefined }),
    ).toBeNull();
  });

  test("a staged thread keeps what was staged on it", () => {
    expect(
      seatPermission({ currentId: null, owner: null, stored: undefined }),
    ).toBeNull();
  });

  test("and keeps it through the adoption of a backend id", () => {
    // `mainChat` moves the ownership across as the run reports the new id, so the
    // adoption reads as the same thread rather than as a switch — otherwise the
    // control would drop to the default mid-turn on the very thread it created.
    expect(
      seatPermission({
        currentId: "new-id",
        owner: "new-id",
        stored: undefined,
      }),
    ).toBeNull();
  });
});
