import { describe, expect, test } from "bun:test";
import { parseShellOutput, toTerminalOutcome } from "./data/mappers";
import { terminalResult } from "./toolPresentation";

/**
 * Which tools render as a terminal, and how each one's result becomes one.
 *
 * The table is the point. The fold used to ask `name === code_run_host_command` in four
 * separate event cases, so the worktree shell — code mode's only way to run anything at
 * all — fell through to a generic tool card while carrying the terminal glyph.
 */

describe("the table says which calls are terminals", () => {
  test("both tools that run a command", () => {
    expect(terminalResult("code_run_host_command")).toBe("record");
    expect(terminalResult("shell_run_command")).toBe("text");
  });

  test("and nothing else", () => {
    // `start_command` deliberately included: a background process is a handle the
    // agent checks on later, not output the operator watches arrive.
    expect(terminalResult("shell_start_command")).toBeUndefined();
    expect(terminalResult("shell_check_command")).toBeUndefined();
    expect(terminalResult("code_execute")).toBeUndefined();
    expect(terminalResult("files_read_file")).toBeUndefined();
    expect(terminalResult("external_linear_create_issue")).toBeUndefined();
  });
});

describe("the sandboxed host tool answers with a record", () => {
  test("each stream lands in its own slot", () => {
    expect(
      toTerminalOutcome("record", {
        exit_code: 0,
        stdout: "hello\n",
        stderr: "",
      }),
    ).toEqual({
      phase: "ok",
      exitCode: 0,
      stdout: "hello\n",
      stderr: "",
      timedOut: undefined,
      error: undefined,
    });
  });

  test("a plain string is not output there — it is a denial", () => {
    // The tool always returns a record when it actually executes, so a string means
    // it never ran. `toHostCommand` turns this null into a denied terminal rather
    // than a green OK.
    expect(toTerminalOutcome("record", "Denied by the operator.")).toBeNull();
  });
});

describe("the worktree shell answers with one labelled string", () => {
  test("stdout alone", () => {
    expect(parseShellOutput("[stdout]\nhello\n")).toEqual({
      phase: "ok",
      exitCode: 0,
      stdout: "hello\n",
      stderr: undefined,
    });
  });

  test("both streams, split at the label", () => {
    expect(parseShellOutput("[stdout]\nout\n[stderr]\nerr")).toEqual({
      phase: "ok",
      exitCode: 0,
      stdout: "out",
      stderr: "err",
    });
  });

  test("a non-zero exit is lifted out of the text and fails the terminal", () => {
    expect(parseShellOutput("[stderr]\nboom\n[exit code: 2]")).toEqual({
      phase: "error",
      exitCode: 2,
      stdout: undefined,
      stderr: "boom",
    });
  });

  test("a command that printed nothing still reports its exit", () => {
    expect(parseShellOutput("(no output)")).toEqual({
      phase: "ok",
      exitCode: 0,
      stdout: undefined,
      stderr: undefined,
    });
  });

  test("a timeout is a failure, not empty output", () => {
    const out = parseShellOutput("[Command timed out after 300.0s]");
    expect(out.phase).toBe("error");
    expect(out.timedOut).toBe(true);
  });

  test("a shape this build does not know is shown, never swallowed", () => {
    // The format belongs to the shell harness, not to us. If it changes, the
    // terminal has to degrade to raw text — a terminal that renders nothing at all
    // would hide the one thing the operator most needs to see.
    expect(parseShellOutput("something else entirely").stdout).toBe(
      "something else entirely",
    );
  });

  test("a result that is not a string at all yields no outcome", () => {
    expect(toTerminalOutcome("text", { exit_code: 0 })).toBeNull();
  });
});
