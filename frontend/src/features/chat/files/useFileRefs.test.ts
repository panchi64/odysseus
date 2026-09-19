import { describe, expect, test } from "bun:test";
import { namesPath } from "./useFileRefs";

/**
 * The rule that decides whether a staged reference still rides the send.
 *
 * It is a **token** match, not a substring one, and the cases that matter are the ones
 * where those two disagree — a path that is a prefix of another. The backend applies the
 * same rule when carrying references through an edit (`routes/chat._names_path`); if one
 * of the two changes, these are what should fail.
 */
describe("namesPath", () => {
  test("the plain case: the message names the file", () => {
    expect(namesPath("look at @src/a.ts", "src/a.ts")).toBe(true);
    expect(namesPath("@src/a.ts is the one", "src/a.ts")).toBe(true);
  });

  test("a path the operator typed past is no longer named", () => {
    // The whole reason this is not `includes`: the message names a different file.
    expect(namesPath("look at @src/a.tsx", "src/a.ts")).toBe(false);
    expect(namesPath("@src/a.ts.bak", "src/a.ts")).toBe(false);
  });

  test("a deeper path is not named by its own parent's reference", () => {
    expect(namesPath("@src/a/b.ts", "src/a")).toBe(false);
  });

  test("ordinary punctuation after a path still ends it", () => {
    // These close a sentence rather than continue a filename, so the reference holds.
    for (const text of [
      "check @src/a.ts, then stop",
      "check @src/a.ts.",
      "(@src/a.ts)",
      'see "@src/a.ts"',
      "read @src/a.ts; it is short",
    ]) {
      expect(namesPath(text, "src/a.ts")).toBe(true);
    }
  });

  test("a later occurrence counts when an earlier one was a prefix", () => {
    // The scan must not stop at the first hit: the operator wrote both.
    expect(namesPath("@src/a.tsx and @src/a.ts", "src/a.ts")).toBe(true);
  });

  test("a message that does not mention it at all", () => {
    expect(namesPath("never mind the file", "src/a.ts")).toBe(false);
    expect(namesPath("src/a.ts without the at-sign", "src/a.ts")).toBe(false);
  });
});
