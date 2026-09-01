import { describe, expect, test } from "bun:test";
import { createRoot, createSignal } from "solid-js";
import { createStore } from "solid-js/store";
import { groupBlocks } from "../blocks";
import type { AssistantBlock, ChatMessage } from "../model";
import { createApprovalOps } from "./approvals";
import { createFolder } from "./fold";

/**
 * A question parks a run the same way an approval does, and is answered in the same
 * place. What is worth pinning is the seam between those two facts: the block is folded
 * into the transcript (so a reconnect's replay rebuilds the dock), but never *rendered*
 * there (so one park is never two surfaces with two submit buttons for a run that
 * resumes once).
 */

function ask(over: Partial<ChatMessage> = {}, ...blocks: AssistantBlock[]) {
  return {
    id: "a1",
    role: "assistant",
    content: "",
    blocks,
    createdAt: "",
    ...over,
  } as ChatMessage;
}

const question = (stale = false): AssistantBlock => ({
  kind: "question",
  id: "q1",
  question: {
    toolCallId: "t1",
    stale,
    questions: [
      {
        question: "Which database?",
        multiSelect: false,
        options: [{ label: "Postgres" }, { label: "SQLite" }],
      },
    ],
  },
});

const approval = (stale = false): AssistantBlock => ({
  kind: "approval",
  id: "ap1",
  approval: {
    toolCallId: "t2",
    name: "shell_run_command",
    args: {},
    summary: "Runs ls",
    stale,
  },
});

function ops(messages: ChatMessage[], sending = true) {
  return createRoot((dispose) => {
    const [store] = createStore<ChatMessage[]>(messages);
    const [live] = createSignal(sending);
    const built = createApprovalOps({
      messages: store,
      patchById: () => {},
      sending: live,
      reconcileStaleDecision: async () => {},
    });
    const answer = { park: built.park(), waiting: built.awaitingInput() };
    dispose();
    return answer;
  });
}

describe("what the dock is handed", () => {
  test("an unanswered question is a park, and the run is waiting", () => {
    const { park, waiting } = ops([ask({ streaming: true }, question())]);
    expect(waiting).toBe(true);
    expect(park?.questions).toHaveLength(1);
    expect(park?.questions[0].questions[0].question).toBe("Which database?");
  });

  test("a park holding both kinds hands over both, under one message", () => {
    // The run resumes on one body covering everything, so the dock has to be able to
    // collect both halves before it submits either.
    const { park } = ops([ask({ streaming: true }, question(), approval())]);
    expect(park?.questions).toHaveLength(1);
    expect(park?.approvals).toHaveLength(1);
    expect(park?.messageId).toBe("a1");
  });

  test("a stale park stays up to explain itself, but stops asking for attention", () => {
    // Putting the composer back on a 409 would claim the run had moved on — which is
    // exactly what is not yet known until the refetch lands.
    const { park, waiting } = ops([ask({ streaming: true }, question(true))]);
    expect(park).not.toBeNull();
    expect(park?.stale).toBe(true);
    expect(waiting).toBe(false);
  });

  test("one stale half stales the whole park — it settles as one submission", () => {
    const { park } = ops([
      ask({ streaming: true }, question(), approval(true)),
    ]);
    expect(park?.stale).toBe(true);
  });

  test("nothing is parked once the run is no longer in flight", () => {
    expect(ops([ask({ streaming: true }, question())], false).park).toBeNull();
  });

  test("a question on an earlier turn does not answer for the live one", () => {
    const { park } = ops([
      ask({ id: "a0" }, question()),
      ask({ id: "a1", streaming: true }),
    ]);
    expect(park).toBeNull();
  });
});

describe("the transcript's side of the seam", () => {
  test("parks are folded but never grouped for rendering", () => {
    // Both halves matter: dropping them from the fold would lose the dock on a
    // reconnect's replay, and grouping them would draw the park twice.
    const groups = groupBlocks([
      { kind: "text", id: "t", text: "hello" },
      question(),
      approval(),
    ]);
    expect(groups.map((g) => g.kind)).toEqual(["text"]);
  });
});

describe("folding question.asked", () => {
  function fold(...events: Record<string, unknown>[]) {
    const message = ask({ streaming: true });
    const foldEvent = createFolder({
      state: {
        maxFoldedSeq: 0,
        foldTarget: null,
        planRevision: 0,
        activeRunId: null,
      },
      patchById: (_id, mutate) => mutate(message),
      setMessages: (() => {}) as never,
      setSnapshots: () => {},
      setBrowserStream: () => {},
      setPlan: () => {},
      setUsage: () => {},
      setStats: () => {},
      setErrored: () => {},
    });
    events.forEach((event, i) =>
      foldEvent("a1", { seq: i + 1, ...event } as never),
    );
    return message;
  }

  test("questions arrive shaped for the panel, with the wire's snake_case gone", () => {
    const folded = fold({
      type: "question.asked",
      tool_call_id: "t9",
      questions: [
        {
          question: "Which extras?",
          multi_select: true,
          options: [{ label: "Auth", description: "Sign-in" }],
        },
      ],
    });
    const block = folded.blocks?.[0];
    expect(block?.kind).toBe("question");
    if (block?.kind !== "question") throw new Error("not a question block");
    expect(block.question.toolCallId).toBe("t9");
    expect(block.question.questions[0].multiSelect).toBe(true);
    expect(block.question.questions[0].options[0].description).toBe("Sign-in");
  });

  test("an answered question stops being a park when its result replays", () => {
    // Re-entering the room replays from seq 0, where the result is the only thing that
    // knows the question was answered — otherwise the dock reopens over a live run.
    const folded = fold(
      { type: "question.asked", tool_call_id: "t9", questions: [] },
      {
        type: "tool.completed",
        tool_call_id: "t9",
        name: "builtin_ask_user",
        result: "Q: Which database?\nA: Postgres",
      },
    );
    expect(folded.blocks?.some((b) => b.kind === "question")).toBe(false);
  });

  test("a decided approval stops being a park too, whether it ran or was denied", () => {
    // A denial comes back as the call's result, not as a failure — both paths retire it.
    const settled = (result: Record<string, unknown>) =>
      fold(
        {
          type: "approval.required",
          tool_call_id: "t2",
          name: "mail_send_email",
          summary: "Sends mail",
          args: {},
        },
        { tool_call_id: "t2", name: "mail_send_email", ...result },
      );
    for (const outcome of [
      { type: "tool.completed", result: "sent" },
      { type: "tool.completed", result: "The operator denied this." },
      { type: "tool.failed", error: "boom" },
    ])
      expect(settled(outcome).blocks?.some((b) => b.kind === "approval")).toBe(
        false,
      );
  });

  test("one settled call does not retire the park beside it", () => {
    // An approval can grant and run while the question beside it is still waiting.
    const folded = fold(
      { type: "question.asked", tool_call_id: "t9", questions: [] },
      {
        type: "approval.required",
        tool_call_id: "t2",
        name: "mail_send_email",
        summary: "Sends mail",
        args: {},
      },
      { type: "tool.completed", tool_call_id: "t2", name: "mail_send_email" },
    );
    expect(folded.blocks?.some((b) => b.kind === "approval")).toBe(false);
    expect(folded.blocks?.some((b) => b.kind === "question")).toBe(true);
  });

  test("a call that arrives with nothing in it still folds", () => {
    // The payload is untrusted JSON; a missing list must default in the mapper rather
    // than throw somewhere downstream that has no idea why it is empty.
    const folded = fold({ type: "question.asked", tool_call_id: "t9" });
    const block = folded.blocks?.[0];
    if (block?.kind !== "question") throw new Error("not a question block");
    expect(block.question.questions).toEqual([]);
  });
});
