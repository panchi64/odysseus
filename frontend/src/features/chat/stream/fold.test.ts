import { describe, expect, spyOn, test } from "bun:test";
import { createStore } from "solid-js/store";
import {
  CONTEXT_OVERFLOW_AFTER_FOLD_DETAIL,
  CONTEXT_OVERFLOW_DETAIL,
  type RunEvent,
} from "~/lib/stream";
import { toast } from "~/ui";
import type { ChatMessage, CompactionProgressBlock } from "../model";
import { createFolder, type FoldState, type SubagentRun } from "./fold";
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
  // The conversation-scoped halves the fold writes through a setter rather than onto a
  // message. Held as a plain box here, which is all the signal is from the fold's side.
  let subagents: SubagentRun[] = [];
  const fold = createFolder({
    state,
    patchById: createPatchById(messages, setMessages),
    setMessages,
    setSnapshots: () => {},
    setSubagents: (fn) => {
      subagents = fn(subagents);
    },
    setPlan: () => {},
    setUsage: () => {},
    setStats: () => {},
    setErrored: () => {},
  });
  return {
    fold: (ev: RunEvent) => fold("a1", ev),
    messages,
    subagents: () => subagents,
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

describe("the roster of sub-agents a thread delegated to", () => {
  // Scoped to this block: the module-level `started`/`completed` above belong to the
  // compaction pair, and a delegation's frames are a different protocol entirely.
  const opened = (
    id: string,
    name = "explorer",
    task = "find the config",
  ): RunEvent => ({
    type: "subagent.started",
    seq: ++seq,
    ts: "",
    subagent_id: id,
    agent_name: name,
    task,
    tool_call_id: "call-7",
  });

  const progressed = (id: string, partial: string): RunEvent => ({
    type: "subagent.progress",
    seq: ++seq,
    ts: "",
    subagent_id: id,
    partial,
  });

  const finished = (id: string, summary: string, ms = 4200): RunEvent => ({
    type: "subagent.completed",
    seq: ++seq,
    ts: "",
    subagent_id: id,
    summary,
    duration_ms: ms,
  });

  const failed = (id: string, error: string): RunEvent => ({
    type: "subagent.failed",
    seq: ++seq,
    ts: "",
    subagent_id: id,
    error,
  });

  test("a started frame opens a row carrying what the sub-agent was asked", () => {
    const h = harness(turn());
    h.fold(opened("run-1:call-7:1", "worker", "add the flag"));
    expect(h.subagents()).toEqual([
      {
        id: "run-1:call-7:1",
        name: "worker",
        task: "add the flag",
        toolCallId: "call-7",
        status: "running",
      },
    ]);
  });

  test("progress is latest-wins, not a log", () => {
    // The backend sends a line per child event. A row says where a sub-agent has got
    // to; accumulating them would make the roster a second transcript.
    const h = harness(turn());
    h.fold(opened("s1"));
    h.fold(progressed("s1", "explorer: reading app.py"));
    h.fold(progressed("s1", "explorer: reading settings.py"));
    expect(h.subagents()[0].partial).toBe("explorer: reading settings.py");
  });

  test("completing settles the row and drops the mid-flight line", () => {
    const h = harness(turn());
    h.fold(opened("s1"));
    h.fold(progressed("s1", "explorer: reading app.py"));
    h.fold(finished("s1", "It lives in core/config.py", 1234));
    const row = h.subagents()[0];
    expect(row.status).toBe("completed");
    expect(row.summary).toBe("It lives in core/config.py");
    expect(row.durationMs).toBe(1234);
    // Keeping it would show the last thing it was doing where its report belongs.
    expect(row.partial).toBeUndefined();
  });

  test("failing settles the row too, with the reason", () => {
    // The case the whole `finally` on the backend exists for: without this frame the
    // row sits on "running" for the rest of the conversation.
    const h = harness(turn());
    h.fold(opened("s1"));
    h.fold(failed("s1", "the fork went away"));
    const row = h.subagents()[0];
    expect(row.status).toBe("failed");
    expect(row.error).toBe("the fork went away");
    expect(row.summary).toBeUndefined();
  });

  test("a retried delegation is a second row, not the first one again", () => {
    // Both delegations share one `tool_call_id` — the model re-issuing the same call —
    // so the sequence in the id is the only thing keeping them apart.
    const h = harness(turn());
    h.fold(opened("run-1:call-7:1"));
    h.fold(finished("run-1:call-7:1", "nothing found"));
    h.fold(opened("run-1:call-7:2"));
    expect(h.subagents().map((s) => s.status)).toEqual([
      "completed",
      "running",
    ]);
  });

  test("a replayed started frame does not open a second row", () => {
    // A reattach replays the run's whole buffer, so the row can already be there. The
    // seq guard drops most of it; the id dedupe is what covers a replay onto a list
    // that survived the run it was built from.
    const h = harness(turn());
    h.fold(opened("s1"));
    h.fold(opened("s1"));
    expect(h.subagents()).toHaveLength(1);
  });

  test("a close for a sub-agent nothing opened is ignored", () => {
    // A `Last-Event-ID` resume can land past the `subagent.started`. There is no name
    // and no task to build a row from, and a row saying only "something finished" is
    // worse than none.
    const h = harness(turn());
    h.fold(finished("s-unknown", "done"));
    expect(h.subagents()).toEqual([]);
  });

  test("the delegating call still folds onto the transcript as its own tool card", () => {
    // The point of the pair: the sub-agent frames are an addition, not a migration. The
    // transcript reads the flattened `tool.progress` line under the call that made it,
    // and the roster reads the structured frames — neither can be rebuilt from the
    // other, because every delegation on one call flattens onto one `tool_call_id`.
    const h = harness(turn());
    h.fold({
      type: "tool.started",
      seq: ++seq,
      ts: "",
      tool_call_id: "call-7",
      name: "agents_delegate_task",
      args: { agent_name: "explorer", task: "find the config" },
    });
    h.fold(opened("run-1:call-7:1"));
    h.fold({
      type: "tool.progress",
      seq: ++seq,
      ts: "",
      tool_call_id: "call-7",
      elapsed_s: null,
      partial: "explorer: reading app.py",
    });
    h.fold(progressed("run-1:call-7:1", "explorer: reading app.py"));

    const card = (h.messages.find((m) => m.id === "a1")?.blocks ?? []).find(
      (b) => b.kind === "tool",
    );
    expect(card?.kind === "tool" && card.tool.progress).toBe(
      "explorer: reading app.py",
    );
    expect(h.subagents()[0].partial).toBe("explorer: reading app.py");
  });
});
