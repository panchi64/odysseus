import { describe, expect, test } from "bun:test";
import type { AssistantBlock, ChatMessage } from "./model";
import { nextPinned, streamTick } from "./transcriptScroll";

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

/**
 * Letting go of the stream.
 *
 * The rule this replaced yielded on distance alone, and the bug it caused is the one
 * case worth naming in a test: a scroll-up smaller than the re-attach threshold left the
 * follow attached, so the next fragment put the view straight back at the bottom and the
 * transcript could not be left while a turn ran.
 */
describe("the follow lets go of any upward movement it did not cause", () => {
  /** Pinned at the bottom of a 5000px transcript in an 800px viewport. */
  const atBottom = {
    pinned: true,
    lastTop: 4200,
    lastHeight: 5000,
    top: 4200,
    height: 5000,
    clientHeight: 800,
  };

  test("a 40px nudge up detaches, though it stays inside ATTACHED_PX", () => {
    expect(nextPinned({ ...atBottom, top: 4160 })).toBe(false);
  });

  test("even a 3px nudge detaches — there is no gesture to out-scroll", () => {
    expect(nextPinned({ ...atBottom, top: 4197 })).toBe(false);
  });

  test("sub-pixel drift does not", () => {
    expect(nextPinned({ ...atBottom, top: 4199 })).toBe(true);
  });

  test("the follow's own write is not read back as movement", () => {
    // `followBottom` records where it put the container, so the scroll event it
    // provokes arrives with `top === lastTop`.
    const grown = { ...atBottom, lastTop: 4700, top: 4700, height: 5500 };
    expect(nextPinned(grown)).toBe(true);
  });

  test("content growing under a detached transcript leaves it detached", () => {
    const detached = {
      ...atBottom,
      pinned: false,
      lastTop: 1000,
      top: 1000,
      height: 5500,
    };
    expect(nextPinned(detached)).toBe(false);
  });

  test("a fold closing clamps the view up without detaching", () => {
    // The one upward movement the operator did not ask for: `scrollHeight` shrinks
    // below `scrollTop` and the browser pulls the view back on its own.
    expect(
      nextPinned({ ...atBottom, top: 3400, height: 4200, lastHeight: 5000 }),
    ).toBe(true);
  });

  test("scrolling back to the bottom re-attaches", () => {
    const returning = {
      ...atBottom,
      pinned: false,
      lastTop: 1000,
      top: 4150,
      height: 5000,
    };
    expect(nextPinned(returning)).toBe(true);
  });

  test("scrolling down but not all the way back stays detached", () => {
    const returning = {
      ...atBottom,
      pinned: false,
      lastTop: 1000,
      top: 3000,
      height: 5000,
    };
    expect(nextPinned(returning)).toBe(false);
  });
});
