import { describe, expect, test } from "bun:test";
import { recallStep } from "./queuedRecall";

// Three ids in transcript order, oldest first. Named out of alphabetical order so a
// walk that sorted instead of following the list would land on the wrong one.
const ORDER = ["q-c", "q-a", "q-b"] as const;

describe("recallStep", () => {
  test("entering from nothing opens the newest", () => {
    expect(recallStep(ORDER, null, "older")).toBe("q-b");
  });

  test("an empty queue has nothing to open", () => {
    expect(recallStep([], null, "older")).toBeNull();
  });

  test("newer from nothing stays out", () => {
    expect(recallStep(ORDER, null, "newer")).toBeNull();
  });

  test("older walks back through transcript order", () => {
    expect(recallStep(ORDER, "q-b", "older")).toBe("q-a");
    expect(recallStep(ORDER, "q-a", "older")).toBe("q-c");
  });

  test("older stops at the oldest", () => {
    expect(recallStep(ORDER, "q-c", "older")).toBeNull();
  });

  test("newer walks forward and steps out past the newest", () => {
    expect(recallStep(ORDER, "q-c", "newer")).toBe("q-a");
    expect(recallStep(ORDER, "q-b", "newer")).toBeNull();
  });

  test("a current that left the list counts as nothing open", () => {
    expect(recallStep(ORDER, "q-gone", "older")).toBe("q-b");
    expect(recallStep(ORDER, "q-gone", "newer")).toBeNull();
  });
});
