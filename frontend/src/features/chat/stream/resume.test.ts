import { describe, expect, test } from "bun:test";
import type { ConversationDetailDTO } from "../data/wire";
import type { ChatMessage } from "../model";
import { createResumeOps, type ResumeDeps } from "./resume";

/**
 * The stale-thread guard, which is the whole reason these four reconcilers live in one
 * file.
 *
 * Each of them has an `await` in the middle, and the store on the other side of it
 * belongs to whichever thread is open *then*. Reseating one thread's history over
 * another's replaces the transcript of a turn that is still streaming and freezes it —
 * so "the operator switched threads while the read was in flight" is the case that has
 * to be written down, and it was the one written three different ways and forgotten in
 * the fourth.
 *
 * `fetchDetail` is a dependency, so the read resolves exactly when this says it does.
 */

function detailFor(id: string): ConversationDetailDTO {
  return {
    id,
    messages: [],
    active_run: null,
  } as unknown as ConversationDetailDTO;
}

function harness(options: { openAfterFetch?: string | null } = {}) {
  let open: string | null = "A";
  const reseated: string[] = [];
  const reattached: string[] = [];
  const deps: ResumeDeps = {
    conversationId: () => open,
    fetchDetail: async (id) => {
      // The operator moves while the request is in flight.
      if (options.openAfterFetch !== undefined) open = options.openAfterFetch;
      return detailFor(id);
    },
    messages: [] as ChatMessage[],
    setMessages: (() => {}) as ResumeDeps["setMessages"],
    reseat: (d) => reseated.push(d.id),
    reattachRun: async (runId) => {
      reattached.push(runId);
    },
    wasCancelled: () => false,
  };
  return { ops: createResumeOps(deps), reseated, reattached };
}

describe("an answer about a thread the operator has left is dropped", () => {
  test("the lost-run recovery does not reseat over the new thread", async () => {
    // This is the one that had no guard at all: `reattachRun`'s fallback read the
    // detail and reseated with no second look at which thread was open.
    const h = harness({ openAfterFetch: "B" });
    await h.ops.recoverLostRun();
    expect(h.reseated).toEqual([]);
  });

  test("a stale decision does not reseat over the new thread", async () => {
    const h = harness({ openAfterFetch: "B" });
    await h.ops.reconcileStaleDecision();
    expect(h.reseated).toEqual([]);
    expect(h.reattached).toEqual([]);
  });

  test("a 409 re-attach does not contaminate the new thread with the old run", async () => {
    const h = harness({ openAfterFetch: "B" });
    await h.ops.reattachToLiveRun("A");
    expect(h.reattached).toEqual([]);
  });

  test("and adopting server ids does not either", async () => {
    const h = harness({ openAfterFetch: "B" });
    await h.ops.adoptServerMeta();
    expect(h.reseated).toEqual([]);
  });
});

describe("staying on the thread lets the answer through", () => {
  test("the lost-run recovery reseats", async () => {
    const h = harness();
    await h.ops.recoverLostRun();
    expect(h.reseated).toEqual(["A"]);
  });

  test("a stale decision reseats", async () => {
    const h = harness();
    await h.ops.reconcileStaleDecision();
    expect(h.reseated).toEqual(["A"]);
  });
});

test("an unsaved thread has nothing to read", async () => {
  let fetched = false;
  const ops = createResumeOps({
    conversationId: () => null,
    fetchDetail: async () => {
      fetched = true;
      return detailFor("nope");
    },
    messages: [],
    setMessages: (() => {}) as ResumeDeps["setMessages"],
    reseat: () => {},
    reattachRun: async () => {},
    wasCancelled: () => false,
  });
  await ops.recoverLostRun();
  expect(fetched).toBe(false);
});
