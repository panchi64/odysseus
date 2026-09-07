import { describe, expect, test } from "bun:test";
import { commandPrefix, commandScopeLabel, grantKey } from "./commandScope";

describe("commandPrefix", () => {
  test("keeps the program and the leading words", () => {
    expect(commandPrefix("uv run pytest tests/test_a.py -k thing")).toEqual([
      "uv",
      "run",
      "pytest",
    ]);
    expect(commandPrefix("git commit -m x")).toEqual([
      "git",
      "commit",
      "-m",
      "x",
    ]);
    expect(commandPrefix("ls")).toEqual(["ls"]);
  });

  test("stops at three operands, where a prefix starts naming its target", () => {
    expect(commandPrefix("brew install ripgrep --force")).toEqual([
      "brew",
      "install",
      "ripgrep",
    ]);
  });

  test("keeps a flag instead of stopping at it — an option is part of the act", () => {
    // The backend matches a grant on these words, so a label that dropped them would
    // name an act broader than the one being recorded.
    expect(commandPrefix("curl -sS https://api.example/x")).toEqual([
      "curl",
      "-sS",
      "https://api.example/x",
    ]);
    expect(commandPrefix("git --version")).toEqual(["git", "--version"]);
  });

  test("reads an environment assignment as the environment, not as the act", () => {
    // `CI=1 bun test` is `bun test` with a variable set; the backend's walk records the
    // assignment separately, and a label opening with it would name a different act.
    expect(commandPrefix("CI=1 bun test")).toEqual(["bun", "test"]);
    expect(commandPrefix("PYTHONPATH=src uv run pytest")).toEqual([
      "uv",
      "run",
      "pytest",
    ]);
    // Past the program it is an ordinary argument — `env` is being handed it.
    expect(commandPrefix("env FOO=1 curl https://x.test")).toEqual([
      "env",
      "FOO=1",
      "curl",
    ]);
  });

  test("keeps a leading dash that is the program itself", () => {
    // The break is for *arguments*: a first word is the program whatever it looks like,
    // and dropping it would leave the label naming the flag.
    expect(commandPrefix("-x")).toEqual(["-x"]);
  });

  test.each([
    "cat $TARGET",
    "git diff | head",
    "git add . && git commit",
    "echo 'a b'",
    "cat *.py",
    "",
    "   ",
  ])("refuses to name a command it cannot read: %p", (command) => {
    // Anything the shell would expand, quote or chain: the words as written are not the
    // words the program receives, and a pipeline's tail is a second act the label hides.
    expect(commandPrefix(command)).toBeNull();
  });
});

describe("commandScopeLabel", () => {
  test("is the act as one string, or nothing to say", () => {
    expect(commandScopeLabel("uv run pytest -k x")).toBe("uv run pytest");
    expect(commandScopeLabel(undefined)).toBeNull();
    expect(commandScopeLabel("cat $TARGET")).toBeNull();
  });
});

describe("grantKey", () => {
  test("an environment assignment does not split one act into two opt-ins", () => {
    // Both record the same backend grant (`bun test`), so one checkbox is the right
    // count — keying them apart would record a standing yes the operator ticked once.
    expect(grantKey("shell_run_command", "CI=1 bun test", "c1")).toBe(
      grantKey("shell_run_command", "bun test", "c2"),
    );
  });

  test("two commands on one tool are two opt-ins", () => {
    expect(grantKey("shell_run_command", "uv run pytest", "c1")).not.toBe(
      grantKey("shell_run_command", "git commit -m x", "c2"),
    );
  });

  test("the same act asked twice shares one opt-in", () => {
    expect(
      grantKey("shell_run_command", "uv run pytest tests/a.py", "c1"),
    ).toBe(grantKey("shell_run_command", "uv run pytest tests/b.py", "c2"));
  });

  test("a tool that runs no command keys on the tool", () => {
    // The whole-tool grant the backend records for it — one checkbox is the right count.
    expect(grantKey("mail_send", undefined, "c1")).toBe("mail_send");
    expect(grantKey("mail_send", undefined, "c2")).toBe("mail_send");
  });

  test("two commands neither can name are still two opt-ins", () => {
    // The backend's walk reads both and scopes a grant to each, so collapsing them onto
    // the tool would let a tick under one record a standing yes to the other.
    expect(grantKey("shell_run_command", "git commit -m 'a'", "c1")).not.toBe(
      grantKey("shell_run_command", "rm -rf 'tmp'", "c2"),
    );
  });

  test("one unnameable command keeps its own opt-in across renders", () => {
    expect(grantKey("shell_run_command", "cat $TARGET", "c1")).toBe(
      grantKey("shell_run_command", "cat $TARGET", "c1"),
    );
  });
});
