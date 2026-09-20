/** What the Commands surface is looking at.
 *
 *  Two rules, both of which a plausible implementation gets wrong: the order is the
 *  transcript's (a command log read out of sequence is not a log), and a command is
 *  counted as failed when the thread did not get what it asked for — which includes a
 *  refusal, not only a non-zero exit.
 *
 *  The fixtures are ordered to fight the ordering rule: the failure is in the middle,
 *  so a sort that floated it would be visible.
 */

import { describe, expect, test } from "bun:test";
import { collectCommands, failedCount } from "./commandItems";
import type { ChatMessage, HostCommand } from "../model";

const command = (
  id: string,
  phase: HostCommand["phase"],
  line: string,
): HostCommand => ({
  toolCallId: id,
  name: "shell_run_command",
  command: line,
  phase,
});

const turn = (id: string, commands: HostCommand[]): ChatMessage => ({
  id,
  role: "assistant",
  content: "",
  createdAt: "2026-09-20T10:00:00Z",
  blocks: [
    { kind: "thinking", id: `${id}-r`, text: "…" },
    ...commands.map((c) => ({
      kind: "host_command" as const,
      id: `${id}-${c.toolCallId}`,
      command: c,
    })),
    { kind: "text", id: `${id}-t`, text: "done" },
  ],
});

describe("collecting a thread's commands", () => {
  test("every terminal block, in transcript order, across turns", () => {
    const messages = [
      turn("m1", [
        command("a", "ok", "git status"),
        command("b", "error", "bun run test"),
      ]),
      { id: "m2", role: "user", content: "fix it", createdAt: "x" },
      turn("m3", [command("c", "ok", "bun run lint")]),
    ] as ChatMessage[];
    expect(collectCommands(messages).map((c) => c.command)).toEqual([
      "git status",
      "bun run test",
      "bun run lint",
    ]);
  });

  test("a turn with no blocks contributes nothing", () => {
    expect(
      collectCommands([
        { id: "m", role: "user", content: "hi", createdAt: "x" },
      ] as ChatMessage[]),
    ).toEqual([]);
  });

  test("a refusal counts as a failure, a pending call does not", () => {
    // "Did this thread get what it asked for" is the question, so a command the
    // operator denied did not run any more than one that exited non-zero did. A
    // command still waiting on an answer has not failed at anything yet.
    const commands = [
      command("a", "ok", "git status"),
      command("b", "error", "bun run test"),
      command("c", "denied", "rm -rf build"),
      command("d", "pending", "git push"),
      command("e", "running", "bun run build"),
    ];
    expect(failedCount(commands)).toBe(2);
  });
});
