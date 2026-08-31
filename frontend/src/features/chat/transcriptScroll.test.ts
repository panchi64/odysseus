import { describe, expect, test } from "bun:test";
import type { AssistantBlock, ChatMessage } from "./model";
import { streamTick } from "./transcriptScroll";

/**
 * The tick is what makes the transcript follow a turn that is growing *inside* its last
 * message rather than gaining messages. So the thing worth testing is not the number —
 * it is meaningless — but that every way a turn can change moves it.
 *
 * The mutation cases are the ones that bite: a block filled in after it was pushed
 * leaves the block *count* alone, so a kind that falls through to the flat `+1` arm is
 * one the view stops following the moment its row starts growing.
 */
function turn(...blocks: AssistantBlock[]): ChatMessage[] {
  return [
    { id: "u1", role: "user", content: "go", createdAt: "" },
    { id: "a1", role: "assistant", content: "", blocks, createdAt: "" },
  ];
}

const review = (over: Partial<AssistantBlock & object> = {}): AssistantBlock =>
  ({
    kind: "review",
    id: "review-1",
    review: { toolCallId: "t1", name: "shell_run_command", summary: "Runs ls" },
    ...over,
  }) as AssistantBlock;

describe("every fragment that grows the turn moves the tick", () => {
  test("answer text", () => {
    const before = streamTick(turn({ kind: "text", id: "t", text: "Hel" }));
    const after = streamTick(turn({ kind: "text", id: "t", text: "Hello" }));
    expect(after).not.toBe(before);
  });

  test("a review row appearing", () => {
    expect(streamTick(turn(review()))).not.toBe(streamTick(turn()));
  });

  test("a review row being FILLED IN", () => {
    // `review.completed` mutates the block `review.started` already pushed: same block
    // count, more row. Without a case of its own this landed on the flat `+1` arm, the
    // tick never moved, and the transcript sat still while the verdict expanded the row
    // it was pinned to the bottom of.
    const started = streamTick(turn(review()));
    const settled = streamTick(
      turn(
        review({
          review: {
            toolCallId: "t1",
            name: "shell_run_command",
            summary: "Runs ls",
            decision: "allow",
            stage: "judge",
            reason: "read-only",
          },
        }),
      ),
    );
    expect(settled).not.toBe(started);
  });

  test("an injected context block arriving", () => {
    expect(
      streamTick(
        turn({
          kind: "context",
          id: "ctx-1",
          injection: {
            contributor: "repo",
            placement: "instructions",
            tokens: 40,
            text: "Project instructions",
            truncated: false,
          },
        }),
      ),
    ).not.toBe(streamTick(turn()));
  });

  test("a tool call settling", () => {
    const running = streamTick(
      turn({
        kind: "tool",
        id: "tool-1",
        tool: {
          id: "1",
          name: "files_read_file",
          args: "{}",
          status: "running",
        },
      }),
    );
    const done = streamTick(
      turn({
        kind: "tool",
        id: "tool-1",
        tool: {
          id: "1",
          name: "files_read_file",
          args: "{}",
          status: "ok",
          result: "…",
        },
      }),
    );
    expect(done).not.toBe(running);
  });

  test("host command output", () => {
    const empty = streamTick(
      turn({
        kind: "host_command",
        id: "host-1",
        command: {
          toolCallId: "1",
          name: "shell_run_command",
          command: "ls",
          phase: "running",
        },
      }),
    );
    const withOutput = streamTick(
      turn({
        kind: "host_command",
        id: "host-1",
        command: {
          toolCallId: "1",
          name: "shell_run_command",
          command: "ls",
          phase: "running",
          stdout: "a\nb\n",
        },
      }),
    );
    expect(withOutput).not.toBe(empty);
  });
});

test("an empty transcript is answerable", () => {
  expect(streamTick([])).toBe(0);
});
