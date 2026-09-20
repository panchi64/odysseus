import { describe, expect, test } from "bun:test";
import { groupByDirectory } from "./fileTreeRows";

/**
 * Grouping flat paths into a readable tree. Pure presentation — the one rule that
 * actually matters is that it never re-orders, because both lists it is given
 * (a ranked listing, a ranked diff) arrive in an order the backend decided.
 */
describe("groupByDirectory", () => {
  test("a directory heading appears once, where its first file does", () => {
    const rows = groupByDirectory([
      "src/a.ts",
      "src/b.ts",
      "docs/x.md",
      "src/c.ts",
    ]);
    // `src` is headed twice on purpose: the paths return to it after `docs`, and
    // hoisting them together would be re-ordering a ranked list.
    expect(rows.map((r) => `${r.kind}:${r.key}`)).toEqual([
      "dir:dir:src",
      "file:src/a.ts",
      "file:src/b.ts",
      "dir:dir:docs",
      "file:docs/x.md",
      "dir:dir:src",
      "file:src/c.ts",
    ]);
  });

  test("the ranked order of files is preserved exactly", () => {
    // The fixture is ordered to fight the rule: alphabetical would put `a` first.
    const ranked = ["z/one.ts", "a/two.ts", "z/three.ts"];
    const files = groupByDirectory(ranked).filter((r) => r.kind === "file");
    expect(files.map((r) => (r.kind === "file" ? r.path : ""))).toEqual(ranked);
  });

  test("a file under a heading prints its basename, not its whole path", () => {
    const rows = groupByDirectory(["src/features/chat/model.ts"]);
    const file = rows.find((r) => r.kind === "file");
    expect(file).toMatchObject({
      label: "model.ts",
      path: "src/features/chat/model.ts",
      depth: 1,
    });
  });

  test("a root-level file gets no invented heading and keeps its whole path", () => {
    // Naming a heading "/" or "root" would show the operator a directory that appears
    // in none of their paths.
    const rows = groupByDirectory(["README.md", "src/a.ts"]);
    expect(rows[0]).toMatchObject({
      kind: "file",
      label: "README.md",
      depth: 0,
    });
    expect(rows[1]).toMatchObject({ kind: "dir", name: "src" });
  });

  test("the heading is the full relative directory, not one row per segment", () => {
    const rows = groupByDirectory(["a/b/c/deep.ts"]);
    expect(rows.filter((r) => r.kind === "dir")).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "dir", name: "a/b/c" });
  });

  test("an empty listing produces no rows at all", () => {
    expect(groupByDirectory([])).toEqual([]);
  });
});
