import { describe, expect, test } from "bun:test";
import {
  DEFAULT_PERMISSION_LEVEL,
  PERMISSION_LEVELS,
  STRICTEST_PERMISSION_LEVEL,
} from "./model";
import { seatPermission } from "./permissionSeat";

describe("a thread's level never rides another thread's send", () => {
  test("opening a different thread drops to the strictest before its history lands", () => {
    // The bug this rule exists for: sitting in thread A at auto, click thread B, send
    // before the fetch answers. The level in hand is A's, the id on the wire is B's,
    // and the backend persists what it is sent — so B, which the operator had set to
    // plan, comes back auto-approving with nothing on screen having said so.
    expect(
      seatPermission({ currentId: "B", owner: "A", stored: undefined }),
    ).toEqual({
      owner: "B",
      level: STRICTEST_PERMISSION_LEVEL,
      // And it says it is a placeholder, not the thread's answer — the composer's control
      // renders pending on this rather than flashing PLAN on every thread open, which
      // would be indistinguishable from a thread genuinely stored at Plan.
      provisional: true,
    });
  });

  test("and the fallback is the narrowest level, not the default one", () => {
    // The two were the same value once and the assertion above passed either way. They
    // are not any more — the default is Auto, the widest level there is — so a fallback
    // spelled `DEFAULT_PERMISSION_LEVEL` would *be* the escalation this rule prevents.
    expect(STRICTEST_PERMISSION_LEVEL).toBe(PERMISSION_LEVELS[0].id);
    expect(STRICTEST_PERMISSION_LEVEL).not.toBe(DEFAULT_PERMISSION_LEVEL);
  });

  test("the same window opening from a staged composer", () => {
    // Same window, reached the other way: a level chosen on the unsaved composer is
    // owned by no thread, and must not follow the operator into one.
    expect(
      seatPermission({ currentId: "B", owner: null, stored: undefined }),
    ).toEqual({
      owner: "B",
      level: STRICTEST_PERMISSION_LEVEL,
      provisional: true,
    });
  });

  test("the loaded thread's own level wins once it arrives", () => {
    // And it is an answer, not a placeholder: the control leaves its pending state the
    // moment the thread has spoken for itself, whatever it says.
    expect(
      seatPermission({ currentId: "B", owner: "B", stored: "plan" }),
    ).toEqual({ owner: "B", level: "plan", provisional: false });
  });

  test("starting a new thread returns to the default", () => {
    // The other half of the rule, and the reason the fallback is not one constant: an
    // unsaved thread has no stored level coming, so there is nothing to be strict on
    // behalf of — it starts where every fresh thread starts.
    expect(
      seatPermission({ currentId: null, owner: "A", stored: undefined }),
    ).toEqual({
      owner: null,
      level: DEFAULT_PERMISSION_LEVEL,
      // Nothing is coming for an unsaved thread, so this default *is* the answer and the
      // control names it — a fresh composer must not sit on a pending control forever.
      provisional: false,
    });
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
