import { describe, expect, spyOn, test } from "bun:test";
import { createStore } from "solid-js/store";
import {
  CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL,
  CONTEXT_OVERFLOW_DETAIL,
  type RunEvent,
} from "~/lib/stream";
import { toast } from "~/ui";
import type { ChatMessage, CompactionProgress } from "../model";
import { FOLD_RUN_KIND, createFolder, type FoldState } from "./fold";
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
    tasksRevision: 0,
    planRevision: 0,
    activeRunId: "run-1",
    runKind: null,
  };
  const fold = createFolder({
    state,
    patchById: createPatchById(messages, setMessages),
    setMessages,
    setSnapshots: () => {},
    setTasks: () => {},
    setPlan: () => {},
    setPermission: () => {},
    setUsage: () => {},
    setStats: () => {},
    setErrored: () => {},
    setTitlePending: () => {},
  });
  return {
    fold: (ev: RunEvent) => fold("a1", ev),
    messages,
  };
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

/** Every fold still in flight, in order — a compaction turn that has live state on it. */
function live(messages: ChatMessage[]): CompactionProgress[] {
  return messages
    .filter((m) => m.role === "compaction" && m.compaction)
    .map((m) => m.compaction!);
}

const delta = (text: string, part = 1, parts = 1): RunEvent =>
  ({
    type: "compaction.delta",
    seq: ++seq,
    ts: "",
    conversation_id: "c1",
    text,
    part,
    parts,
  }) as RunEvent;

describe("a fold in flight is a turn in the transcript", () => {
  test("the turn opens unfinished, carrying what is going into the fold", () => {
    const h = harness(turn());
    h.fold(started("threshold"));
    expect(live(h.messages)).toEqual([
      { reason: "threshold", messages: 12, tokensEstimate: 40_000 },
    ]);
  });

  test("it opens even with no assistant turn to hang off", () => {
    // The whole reason this is a turn rather than a row on the assistant's rail. A fold
    // the operator starts by hand runs between turns, so there is no assistant message
    // in flight — and the rail version drew nothing at all on that path, which is the
    // defect that started this.
    const h = harness([]);
    h.fold(started("manual"));
    expect(live(h.messages).map((c) => c.reason)).toEqual(["manual"]);
  });

  test("the summary streams into the live turn as it is written", () => {
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(delta("what "));
    h.fold(delta("happened"));
    expect(live(h.messages)[0].summary).toBe("what happened");
  });

  test("a chunked fold says which pass is writing", () => {
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(delta("part one", 1, 3));
    expect(live(h.messages)[0]).toMatchObject({ part: 1, parts: 3 });
  });

  test("the summary landing replaces the live turn with the settled one", () => {
    // The live text is the model's raw working — unstripped, unfenced. Once the real
    // summary lands, keeping both would show the operator two versions of one fold and
    // leave the unsafe one on screen.
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(delta("draft"));
    h.fold(compacted("chk-1", "threshold"));
    expect(live(h.messages)).toHaveLength(0);
    expect(h.messages.find((m) => m.id === "chk-1")?.role).toBe("compaction");
  });

  test("two folds in one turn are two pauses, one at a time", () => {
    // Real after the overflow retry landed: the prelude can fold at the threshold and
    // the same turn can fold again when the provider still refuses the request. Those
    // are two pauses the operator lived through — and only ever one of them is live.
    const h = harness(turn());
    h.fold(started("threshold"));
    h.fold(compacted("chk-1", "threshold"));
    h.fold(started("overflow", 4));
    expect(live(h.messages).map((c) => c.reason)).toEqual(["overflow"]);
    expect(h.messages.filter((m) => m.role === "compaction")).toHaveLength(2);
  });

  test("a replayed frame does not open a second turn", () => {
    // A reattach replays the run's buffer from seq 0 over a transcript that already
    // folded it. The seq high-water mark is what drops the overlap.
    const h = harness(turn());
    const ev = started("threshold");
    h.fold(ev);
    h.fold(ev);
    expect(live(h.messages)).toHaveLength(1);
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

describe("a review's two frames", () => {
  // The pair the operator reads when the chassis answered for them. What is pinned here
  // is that the *grounds* survive the fold, not just the verdict: the declared reach
  // arrives on the opening frame and the tier and the fence arrive on the closing one,
  // and a card that showed only "allowed" would tell them nothing to act on.
  const started = (
    reach: "workspace" | "network" | "host" | null,
    detail: string | null = null,
  ): RunEvent => ({
    type: "review.started",
    seq: ++seq,
    ts: "",
    tool_call_id: "t1",
    name: "shell_run_command",
    summary: "Runs the shell command: uv run pytest",
    detail,
    reach,
  });

  const completed = (
    tier: "read" | "sandbox" | "workspace" | null,
    fenced: boolean,
  ): RunEvent => ({
    type: "review.completed",
    seq: ++seq,
    ts: "",
    tool_call_id: "t1",
    name: "shell_run_command",
    decision: "allow",
    stage: "judge",
    reason: "stays inside the worktree and reaches no network",
    tier,
    fenced,
    risk: null,
    authorization: null,
    correctness: null,
  });

  const review = (messages: ChatMessage[]) =>
    messages.find((m) => m.id === "a1")?.blocks?.[0];

  test("the declared reach lands with the row that opens", () => {
    const h = harness(turn());
    h.fold(started("network"));
    const block = review(h.messages);
    expect(block?.kind).toBe("review");
    expect(block?.kind === "review" && block.review.reach).toBe("network");
    // Nothing is decided yet — the row exists so a review that costs a model call reads
    // as work in flight rather than as a stalled turn.
    expect(block?.kind === "review" && block.review.decision).toBeUndefined();
  });

  test("the content the reviewer ruled on lands with it", () => {
    // For the tools whose act is not written in one line — a delegated task, a skill's
    // replacement text — the reviewer is given a `detail` beyond the summary. The row is
    // where the operator checks a decision made in their place, so it is shown the same
    // material rather than a paraphrase of it.
    const h = harness(turn());
    h.fold(started(null, "task: read the docs"));
    const block = review(h.messages);
    expect(block?.kind === "review" && block.review.detail).toBe(
      "task: read the docs",
    );
  });

  test("and most tools have none, which renders nothing rather than empty", () => {
    const h = harness(turn());
    h.fold(started("workspace"));
    const block = review(h.messages);
    expect(block?.kind === "review" && block.review.detail).toBeUndefined();
  });

  test("the ground and the fence land with the verdict", () => {
    const h = harness(turn());
    h.fold(started("workspace"));
    h.fold(completed("workspace", true));
    const block = review(h.messages);
    expect(block?.kind === "review" && block.review.tier).toBe("workspace");
    expect(block?.kind === "review" && block.review.fenced).toBe(true);
    expect(block?.kind === "review" && block.review.decision).toBe("allow");
  });

  const unrecoverable = (name: string): RunEvent => ({
    type: "review.completed",
    seq: ++seq,
    ts: "",
    tool_call_id: "t1",
    name,
    decision: "ask",
    stage: "reviewer",
    reason: "too_destructive risk, authorization neutral",
    tier: null,
    fenced: true,
    risk: "too_destructive",
    authorization: "neutral",
    correctness: null,
  });

  const asked = (name: string, command?: string): RunEvent => ({
    type: "approval.required",
    seq: ++seq,
    ts: "",
    tool_call_id: "t1",
    name,
    args: command ? { command } : {},
    summary: `Runs ${name}`,
    explanation: null,
  });

  const blockOf = (messages: ChatMessage[], kind: string) =>
    messages.find((m) => m.id === "a1")?.blocks?.find((b) => b.kind === kind);

  test("what the review found rides onto the card that asks", () => {
    // The reviewer's own refusal became a park, so `too_destructive` is a finding the
    // operator now has to read *while deciding* — not on a collapsed row above the prompt.
    const h = harness(turn());
    h.fold(started("workspace"));
    h.fold(unrecoverable("mail_send"));
    h.fold(asked("mail_send"));
    const block = blockOf(h.messages, "approval");
    expect(block?.kind === "approval" && block.approval.risk).toBe(
      "too_destructive",
    );
    expect(block?.kind === "approval" && block.approval.reviewReason).toBe(
      "too_destructive risk, authorization neutral",
    );
  });

  test("it rides onto the terminal too, which is where the shell asks", () => {
    // `git commit --amend` and `rm -rf build` are the acts that earn the word, and every
    // one of them renders as a terminal rather than as an approval card — so a finding
    // carried only onto the latter would never be seen on the calls it was written for.
    const h = harness(turn());
    h.fold(started("workspace"));
    h.fold(unrecoverable("shell_run_command"));
    h.fold(asked("shell_run_command", "git commit --amend"));
    const block = blockOf(h.messages, "host_command");
    expect(block?.kind === "host_command" && block.command.risk).toBe(
      "too_destructive",
    );
    expect(block?.kind === "host_command" && block.command.reviewReason).toBe(
      "too_destructive risk, authorization neutral",
    );
  });

  test("an approval with no review behind it carries no verdict", () => {
    // Every level but Auto: nothing ruled on it first, so there is nothing to show and
    // the card must not imply a review happened.
    const h = harness(turn());
    h.fold(asked("mail_send"));
    const block = blockOf(h.messages, "approval");
    expect(block?.kind === "approval" && block.approval.risk).toBeUndefined();
    expect(
      block?.kind === "approval" && block.approval.reviewReason,
    ).toBeUndefined();
  });

  test("a null tier is an absence, and an unfenced host is a fact worth keeping", () => {
    // Null on the wire means the model stage settled it, so there is no structural
    // ground to name; `fenced: false` is the separate, actionable fact that this
    // machine could not have held the command to what it declared.
    const h = harness(turn());
    h.fold(started(null));
    h.fold(completed(null, false));
    const block = review(h.messages);
    expect(block?.kind === "review" && block.review.tier).toBeUndefined();
    expect(block?.kind === "review" && block.review.reach).toBeUndefined();
    expect(block?.kind === "review" && block.review.fenced).toBe(false);
  });
});

/**
 * A queued message, and whose it is.
 *
 * The operator typing mid-turn and a sub-agent reporting back ride the same road on
 * purpose — the injection point hands a queued message to the *next, not-yet-sent*
 * request, so neither can interrupt a model mid-stream. They must not arrive looking the
 * same. Read as the operator's, a report is words attributed to somebody who has not seen
 * them, offered with edit and withdraw affordances for a message they cannot take back —
 * and a live transcript that disagrees with what the same thread shows after a reload,
 * where the backend labels it from the envelope it was delivered in.
 */
describe("whose queued message it is", () => {
  const queued = (
    text: string,
    source?: "operator" | "subagent",
  ): RunEvent => ({
    type: "message.queued",
    seq: ++seq,
    ts: "",
    message_id: "q1",
    text,
    ...(source === undefined ? {} : { source }),
  });
  const injected = (source?: "operator" | "subagent"): RunEvent => ({
    type: "message.injected",
    seq: ++seq,
    ts: "",
    message_id: "q1",
    ...(source === undefined ? {} : { source }),
  });

  test("an unmarked frame is the operator's, as it always was", () => {
    // An older backend sends no `source` at all, and everything it ever queued was theirs.
    const h = harness(turn());
    h.fold(queued("actually, check the tests too"));
    const bubble = h.messages.find((m) => m.queuedMessageId === "q1");
    expect(bubble?.role).toBe("user");
  });

  test("a sub-agent's report is not the operator speaking", () => {
    const h = harness(turn());
    h.fold(queued("explorer: the parser is in lexer.ts", "subagent"));
    const bubble = h.messages.find((m) => m.queuedMessageId === "q1");
    expect(bubble?.role).toBe("subagent");
    expect(bubble?.content).toBe("explorer: the parser is in lexer.ts");
  });

  test("a report never tags an optimistic bubble the operator is waiting on", () => {
    // Same text, by coincidence or because the operator was reading the panel. Tagging
    // theirs with the report's id would make their own message the one that promotes as
    // a sub-agent's, and leave the report with no bubble at all.
    const h = harness([
      ...turn(),
      {
        id: "u2",
        role: "user",
        content: "same words",
        queuedPending: true,
        createdAt: "",
      },
    ]);
    h.fold(queued("same words", "subagent"));
    expect(
      h.messages.find((m) => m.id === "u2")?.queuedMessageId,
    ).toBeUndefined();
    expect(h.messages.filter((m) => m.queuedMessageId === "q1")).toHaveLength(
      1,
    );
  });

  test("it promotes to a turn of the thread like any other injected message", () => {
    const h = harness(turn());
    h.fold(queued("explorer: nothing there", "subagent"));
    h.fold(injected("subagent"));
    const landed = h.messages.find((m) => m.queuedMessageId === "q1");
    expect(landed?.queuedPending).toBe(false);
    // Still not theirs — what a reload will show, from the envelope it was delivered in.
    expect(landed?.role).toBe("subagent");
  });
});

describe("a fold that declines still says why", () => {
  // The whole point of the button is that a fold is no longer silent, and the most
  // likely way for it to do nothing is the case where it never starts: the thread is
  // not longer than the retained tail, so there is nothing above it to summarize. No
  // `compaction.started` is emitted then, so there is no live turn to clean up — and
  // keying the report on that cleanup made this exact case go quiet again.
  const ended = (detail: string): RunEvent =>
    ({
      type: "run.ended",
      seq: ++seq,
      ts: "",
      outcome: "blocked",
      detail,
    }) as RunEvent;

  const startedRun = (kind: string): RunEvent =>
    ({
      type: "run.started",
      seq: ++seq,
      ts: "",
      run_id: "r1",
      kind,
    }) as RunEvent;

  test("a blocked fold reports the backend's sentence", () => {
    const spy = spyOn(toast, "info");
    const h = harness(turn());
    h.fold(startedRun("compaction"));
    h.fold(ended("Nothing to fold yet."));
    expect(spy).toHaveBeenCalledWith("Nothing to fold yet.");
    spy.mockRestore();
  });

  test("a blocked chat turn does not — it already marks the turn it stopped", () => {
    // A turn carries a persistent "Stopped:" marker with the same detail on it, so a
    // toast here would state the same sentence twice for one event.
    const spy = spyOn(toast, "info");
    const h = harness(turn());
    h.fold(startedRun("chat"));
    h.fold(ended("The context window is full."));
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  test("the kind is spent at the terminal, so the next run does not inherit it", () => {
    // A drive attached past its run's `run.started` (a transport resume) never sees one,
    // and a kind left over from the fold before would report a chat turn's stop twice.
    const spy = spyOn(toast, "info");
    const h = harness(turn());
    h.fold(startedRun(FOLD_RUN_KIND));
    h.fold(ended("Nothing to fold yet."));
    h.fold(ended("The context window is full."));
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
