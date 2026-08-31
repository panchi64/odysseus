import { describe, expect, test } from "bun:test";
import { createStore } from "solid-js/store";
import type { ChatMessage } from "../model";
import { createPatchById } from "./patch";
import { createSteeringOps, type SteeringDeps } from "./steering";

/**
 * The one invariant every path through this module shares: text the operator typed is
 * never dropped.
 *
 * A steering message can end up with no turn to carry it in four ways — the run went
 * terminal before its boundary, the operator cancelled, the POST was refused, or the
 * thread had not been created yet — and the last of those is the one that reads as
 * "nothing happened" rather than as an error. So what is written down here is the
 * *stash*: the composer gets the words back, appended rather than overwritten, and
 * whatever was queued stops pretending to be part of the transcript.
 */

function harness(seed: ChatMessage[] = []) {
  const [messages, setMessages] = createStore<ChatMessage[]>(seed);
  let conversationId: string | null = "A";
  const deps: SteeringDeps = {
    messages,
    setMessages,
    patchById: createPatchById(messages, setMessages),
    conversationId: () => conversationId,
    adoptConversationId: (id) => {
      conversationId = id;
    },
    activeRunId: () => "run-1",
    setSending: () => {},
    selection: () => null,
    driveRun: async () => {},
  };
  return {
    ops: createSteeringOps(deps),
    messages,
    unsave: () => {
      conversationId = null;
    },
  };
}

const queued = (id: string, content: string): ChatMessage => ({
  id,
  role: "user",
  content,
  createdAt: "",
  queuedPending: true,
});

describe("a queued message the run never consumed comes back", () => {
  test("its bubble leaves the transcript and its text reaches the composer", () => {
    const h = harness([
      { id: "u0", role: "user", content: "delivered", createdAt: "" },
      queued("u1", "and one more thing"),
    ]);
    h.ops.restoreUndelivered();
    expect(h.messages.map((m) => m.id)).toEqual(["u0"]);
    expect(h.ops.undeliveredDraft()).toBe("and one more thing");
  });

  test("several are handed back in the order they were queued", () => {
    const h = harness([queued("u1", "first"), queued("u2", "second")]);
    h.ops.restoreUndelivered();
    expect(h.ops.undeliveredDraft()).toBe("first\nsecond");
  });

  test("a second restore appends rather than replacing the first", () => {
    // The composer may not have consumed the prefill yet — overwriting it here is
    // the same lost message this whole path exists to prevent.
    const h = harness([queued("u2", "second")]);
    h.ops.stash("first");
    h.ops.restoreUndelivered();
    expect(h.ops.undeliveredDraft()).toBe("first\nsecond");
  });

  test("nothing pending is a no-op, not an empty prefill", () => {
    // Both the drive's teardown and `cancel` call this, so it has to be safe to
    // call twice on a turn that had no queued messages at all.
    const h = harness([
      { id: "u0", role: "user", content: "hi", createdAt: "" },
    ]);
    h.ops.restoreUndelivered();
    h.ops.restoreUndelivered();
    expect(h.ops.undeliveredDraft()).toBeNull();
    expect(h.messages).toHaveLength(1);
  });

  test("the composer clears it once consumed", () => {
    const h = harness([queued("u1", "text")]);
    h.ops.restoreUndelivered();
    h.ops.clearUndeliveredDraft();
    expect(h.ops.undeliveredDraft()).toBeNull();
  });
});

test("steering a thread that has no backend id yet stashes instead of dropping", async () => {
  // The first turn's POST hasn't resolved, so there is nothing to queue against —
  // and the composer has already cleared itself. This is the path that looks like
  // success from the operator's side while the words go nowhere.
  const h = harness();
  h.unsave();
  await h.ops.sendWhileStreaming("don't lose this");
  expect(h.ops.undeliveredDraft()).toBe("don't lose this");
  expect(h.messages).toHaveLength(0);
});
