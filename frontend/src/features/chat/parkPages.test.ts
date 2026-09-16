/** Cutting a park into pages.
 *
 *  Three things are easy to get wrong here and none of them is visible in a screenshot:
 *  a page order that does not match the order the replies are filed under (the backend
 *  reads them positionally against the parked call), a park that can never be submitted
 *  because a call with nothing in it is waited on forever, and a submission that covers
 *  fewer calls than the park holds — which the run refuses outright, since it resumes on
 *  one body covering all of them.
 */

import { describe, expect, test } from "bun:test";
import {
  allPagesAnswered,
  answersFor,
  isAnswered,
  pageAnswered,
  parkPages,
} from "./parkPages";
import type { Park } from "./stream/approvals";
import type { QuestionSpec } from "./model";

const q = (question: string): QuestionSpec => ({
  question,
  multiSelect: false,
  options: [{ label: "Yes" }, { label: "No" }],
});

const park = (over: Partial<Park> = {}): Park => ({
  messageId: "a1",
  approvals: [],
  planApproval: null,
  questions: [],
  stale: false,
  ...over,
});

const call = (id: string, ...questions: string[]) => ({
  toolCallId: id,
  questions: questions.map(q),
});

describe("the pages a park makes", () => {
  test("questions flatten across calls, in the order they were asked", () => {
    // Two calls asking two each is four pages, not two — the call is a fact about the
    // model's turn and not a unit the operator has any reason to perceive.
    const pages = parkPages(
      park({ questions: [call("c1", "one", "two"), call("c2", "three")] }),
    );
    expect(
      pages.map((p) => (p.kind === "question" ? p.question.question : p.kind)),
    ).toEqual(["one", "two", "three"]);
  });

  test("a question knows which call and which slot it answers", () => {
    // The reply is filed positionally within its call, and the backend checks it
    // against the parked arguments — a page that misreported either would answer one
    // question with another's words.
    const pages = parkPages(
      park({ questions: [call("c1", "one", "two"), call("c2", "three")] }),
    );
    expect(
      pages.map((p) =>
        p.kind === "question" ? `${p.callId}:${p.index}` : p.kind,
      ),
    ).toEqual(["c1:0", "c1:1", "c2:0"]);
  });

  test("approvals are one page, and the last", () => {
    const pages = parkPages(
      park({
        questions: [call("c1", "one")],
        approvals: [
          {
            toolCallId: "t1",
            name: "shell_run_command",
            args: {},
            summary: "ls",
          },
        ],
      }),
    );
    expect(pages.map((p) => p.kind)).toEqual(["question", "approvals"]);
  });

  test("a park with only approvals is the single page it always was", () => {
    const pages = parkPages(
      park({
        approvals: [
          {
            toolCallId: "t1",
            name: "shell_run_command",
            args: {},
            summary: "ls",
          },
        ],
      }),
    );
    expect(pages.map((p) => p.kind)).toEqual(["approvals"]);
  });
});

describe("when the dock may move on", () => {
  const pages = parkPages(park({ questions: [call("c1", "one", "two")] }));

  test("a selection answers, and so does written text alone", () => {
    expect(isAnswered({ selections: ["Yes"] })).toBe(true);
    expect(isAnswered({ selections: [], text: "something else" })).toBe(true);
  });

  test("neither, or whitespace, does not", () => {
    // The backend refuses this body; refusing it here is the same stop, arriving
    // before the operator presses send rather than as a 422 afterwards.
    expect(isAnswered(undefined)).toBe(false);
    expect(isAnswered({ selections: [] })).toBe(false);
    expect(isAnswered({ selections: [], text: "   " })).toBe(false);
  });

  test("a page is answered on its own reply, not on its neighbour's", () => {
    const replies = { c1: [{ selections: ["Yes"] }] };
    expect(pageAnswered(pages[0], replies, false)).toBe(true);
    expect(pageAnswered(pages[1], replies, false)).toBe(false);
    expect(allPagesAnswered(pages, replies, false)).toBe(false);
  });

  test("the approvals page reads the cards' own verdict", () => {
    const withApproval = parkPages(
      park({
        approvals: [
          {
            toolCallId: "t1",
            name: "shell_run_command",
            args: {},
            summary: "ls",
          },
        ],
      }),
    );
    expect(allPagesAnswered(withApproval, {}, false)).toBe(false);
    expect(allPagesAnswered(withApproval, {}, true)).toBe(true);
  });

  test("a call that parsed to no questions does not block the submit", () => {
    // The payload is whatever the model produced. A malformed call makes no page, so
    // there is nothing to click — and counting replies against the call would compare
    // `undefined` to 0 forever, leaving Stop as the only way out of the dock.
    const empty = park({ questions: [call("c1")] });
    expect(parkPages(empty)).toEqual([]);
    expect(allPagesAnswered(parkPages(empty), {}, false)).toBe(true);
  });
});

describe("the body the park submits", () => {
  test("every parked call appears, padded, even one nothing was entered for", () => {
    // The run resumes on one body covering every deferred call; a missing entry is
    // refused outright, so a call with no page must still be named.
    const p = park({ questions: [call("c1", "one", "two"), call("c2")] });
    expect(answersFor(p, { c1: [{ selections: ["Yes"] }] })).toEqual([
      {
        tool_call_id: "c1",
        replies: [{ selections: ["Yes"] }, { selections: [], text: undefined }],
      },
      { tool_call_id: "c2", replies: [] },
    ]);
  });
});
