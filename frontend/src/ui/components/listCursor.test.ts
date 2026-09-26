import { describe, expect, test } from "bun:test";
import { cursorStep } from "./listCursor";

describe("cursorStep", () => {
  test("arrows move one row and wrap at both ends", () => {
    expect(cursorStep("ArrowDown", 1, 4)).toBe(2);
    expect(cursorStep("ArrowDown", 3, 4)).toBe(0);
    expect(cursorStep("ArrowUp", 2, 4)).toBe(1);
    expect(cursorStep("ArrowUp", 0, 4)).toBe(3);
  });

  test("with nothing active, down lands first and up lands last", () => {
    expect(cursorStep("ArrowDown", -1, 4)).toBe(0);
    expect(cursorStep("ArrowUp", -1, 4)).toBe(3);
  });

  test("Home and End jump to the ends", () => {
    expect(cursorStep("Home", 2, 4)).toBe(0);
    expect(cursorStep("End", 0, 4)).toBe(3);
  });

  test("an empty list and any other key leave the cursor alone", () => {
    expect(cursorStep("ArrowDown", -1, 0)).toBeNull();
    expect(cursorStep("Enter", 1, 4)).toBeNull();
    expect(cursorStep("a", 1, 4)).toBeNull();
  });
});
