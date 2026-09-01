import { describe, expect, spyOn, test } from "bun:test";
import { createStore } from "solid-js/store";
import {
  CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL,
  CONTEXT_OVERFLOW_DETAIL,
  type RunEvent,
} from "~/lib/stream";
import { toast } from "~/ui";
import type { ChatMessage, CompactionProgressBlock } from "../model";
import { createFolder, type FoldState } from "./fold";
import { createPatchById } from "./patch";

/**
 * What a fold event does to the transcript.
 *
 * The two compaction frames are the only pair in the protocol where one event *opens*
 * something on screen and a later one settles it, so what is pinned here is the pairing:
 * the row appears when the summarizer starts, stops throbbing when the summary lands,
 * and a turn that folds twice ends up with two rows rather than one that flickered. The
 * divider's own placement rules are older than this change and covered by the backend;
 * what is new is the reason riding across from the event onto the stored message.
 */

function harness(seed: ChatMessage[] = []) {
  const [messages, setMessages] = createStore<ChatMessage[]>(seed);
  const state: FoldState = {
    maxFoldedSeq: 0,
    foldTarget: null,
    planRevision: 0,
    activeRunId: "run-1",
  };
  const fold = createFolder({
    state,
    patchById: createPatchById(messages, setMessages),
    setMessages,
    setSnapshots: () => {},
    setBrowserStream: () => {},
    setPlan: () => {},
    setUsage: () => {},
    setStats: () => {},
    setErrored: () => {},
  });
  return { fold: (ev: RunEvent) => fold("a1", ev), messages };
}

const turn = (): ChatMessage[] => [
  { id: "u1", role: "user", content: "go on", createdAt: "" },
  { id: "a1", role: "assistant", content: "", blocks: [], createdAt: "" },
];

let seq = 0;
const started = (
  reason: "threshold" | "overflow" | "manual",
  messages = 12,
): RunEvent => ({
  type: "compaction.started",
  seq: ++seq,
  ts: "",
  conversation_id: "c1",
  reason,
  messages,
  tokens_estimate: 40_000,
});

const compacted = (
  id: string,
  reason?: "threshold" | "overflow" | "manual",
): RunEvent => ({
  type: "conversation.compacted",
  seq: ++seq,
  ts: "",
  conversation_id: "c1",
  message_id: id,
  summary: "what happened so far",
  messages_compacted: 12,
  tokens_before: 40_000,
  tokens_after: 3_000,
  after_message_id: "u1",
  reason,
});

/** Every compaction row on the assistant turn, in order. */
function rows(
  messages: ChatMessage[],
): CompactionProgressBlock["compaction"][] {
  return (messages.find((m) => m.id === "a1")?.blocks ?? [])
    .filter(
      (b): b is CompactionProgressBlock => b.kind === "compaction_progress",
    )
    .map((b) => b.compaction);
}

describe("a fold in flight is visible on the turn it interrupted", () => {
  test("the row opens unfinished, carrying what is going into the fold", () => {
    const h = harness(turn());
    h.fold(started("threshold"));
    expect(rows(h.messages)).toEqual([
      { reason: "threshold", messages: 12, tokensEstimate: 40_000 },
    ]);
  });

  test("the summary landing settles the row rather than adding a second", () => {
    // The row is the account of the *wait*; once the fold is done the divider states
    // what it cost. A second row here would report the same fold twice in one turn.
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(compacted("chk-1", "threshold"));
    expect(rows(h.messages)).toHaveLength(1);
    expect(rows(h.messages)[0].done).toBe(true);
  });

  test("two folds in one turn are two rows", () => {
    // Real after the overflow retry landed: the prelude can fold at the threshold and
    // the same turn can fold again when the provider still refuses the request. Those
    // are two pauses the operator lived through, not one that repeated.
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(compacted("chk-1", "threshold"));
    h.fold(started("overflow", 4));
    expect(rows(h.messages).map((c) => c.reason)).toEqual([
      "threshold",
      "overflow",
    ]);
    expect(rows(h.messages).map((c) => c.done)).toEqual([true, undefined]);
  });

  test("a replayed frame does not open a second row", () => {
    // A reattach replays the run's buffer from seq 0 over a transcript that already
    // folded it. The seq high-water mark is what drops the overlap.
    const h = harness(turn());
    const ev = started("threshold");
    h.fold(ev);
    h.fold(ev);
    expect(rows(h.messages)).toHaveLength(1);
  });
});

describe("the divider records why the fold happened", () => {
  test("the reason rides from the event onto the stored message", () => {
    const h = harness(turn());
    h.fold(compacted("chk-1", "overflow"));
    const divider = h.messages.find((m) => m.id === "chk-1");
    expect(divider?.role).toBe("compaction");
    expect(divider?.compactionReason).toBe("overflow");
  });

  test("a backend that sends no reason reads as the ordinary fold", () => {
    // The field is optional on the wire only so an older backend still renders. Such a
    // backend has no overflow retry to report, so the threshold is the only thing it
    // could have meant — and a segment that blinks in and out with the backend version
    // would be worse than one that is always there.
    const h = harness(turn());
    h.fold(compacted("chk-1"));
    expect(h.messages.find((m) => m.id === "chk-1")?.compactionReason).toBe(
      "threshold",
    );
  });

  test("the divider is seated after the turn the backend named", () => {
    const h = harness(turn());
    h.fold(compacted("chk-1", "manual"));
    expect(h.messages.map((m) => m.id)).toEqual(["u1", "chk-1", "a1"]);
  });
});

test("the blocked detail the retry control keys on is the backend's exact string", () => {
  // `BlockedFooter` offers "Compact and retry" on an equality test against this, live
  // off `run.ended` and again off the persisted `blocked_reason` after a reload. Drift
  // by one character and the control silently stops appearing — with no error, because
  // every other stop legitimately fails the same test.
  expect(CONTEXT_OVERFLOW_DETAIL).toBe("context window exceeded");
});

describe("the context stop's toast", () => {
  // The toast is the only place the frontend names its own remedy, and there are two
  // context stops: one the "Compact and retry" control can answer, and one it cannot,
  // because the fold it would perform is the one that just failed. The notice carries
  // the same marker the blocked turn does, so the toast and the button agree.
  const notice = (detail: string): RunEvent => ({
    type: "limit.notice",
    seq: ++seq,
    ts: "",
    limit: "context",
    message: "This conversation reached the model's context window.",
    detail,
  });

  test("names the control on a turn that has not folded yet", () => {
    const spy = spyOn(toast, "error");
    harness(turn()).fold(notice(CONTEXT_OVERFLOW_DETAIL));
    expect(spy.mock.calls.at(-1)?.[0]).toContain("Compact and retry");
    spy.mockRestore();
  });

  test("withholds it once the turn has already folded and overran anyway", () => {
    const spy = spyOn(toast, "error");
    harness(turn()).fold(notice(CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL));
    expect(spy.mock.calls.at(-1)?.[0]).not.toContain("Compact and retry");
    spy.mockRestore();
  });
});

test("the after-fold blocked detail is the backend's exact string", () => {
  // `BlockedFooter` offers its control on an equality test against the *other* constant,
  // so this one must stay distinct from it — one character of drift in either direction
  // and a turn that already folded starts offering to fold again.
  expect(CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL).toBe(
    "context window exceeded after compaction",
  );
  expect(CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL).not.toBe(CONTEXT_OVERFLOW_DETAIL);
});
