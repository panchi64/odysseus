/** What each surface has, and whether it may interrupt.
 *
 *  Availability is the cheap half and still worth pinning: it decides which header
 *  buttons exist, so a source that answers wrongly either hides a surface the operator
 *  has content for or offers one that opens onto nothing.
 *
 *  **Arrival is the half with a judgement in it.** The rule is that a plan puts itself on
 *  screen while it is waiting on the operator's answer and otherwise only badges — which
 *  depends on the moment rather than on what kind of surface a plan is. That is the whole
 *  reason arrival is a predicate, and these are the cases that would make a static field
 *  wrong.
 *
 *  It used to be inferred from the thread's permission level, which needed a guard
 *  against the not-yet-loaded stand-in (the stand-in *is* `plan`). The plan now carries
 *  its own status, so the inference and its guard are both gone — and the tests for them
 *  with it.
 */

import { describe, expect, test } from "bun:test";
import { createSurfaceSources, type SurfaceDeps } from "./surfaceSources";
import type { PlanDocument, PlanStatus } from "../model";
import type { TaskItem } from "~/lib/stream/events";
import type { BranchState } from "../data";
import type { ViewItem } from "./viewItems";

const taskItem = (content: string): TaskItem => ({
  id: content,
  content,
  status: "pending",
});

const planDoc = (status: PlanStatus, revision = 1): PlanDocument => ({
  title: "Rewrite the parser",
  body: "## Why\nIt is slow.",
  steps: ["read it", "change it"],
  status,
  revision,
});

const viewItem = (withSnapshot: boolean): ViewItem =>
  ({
    key: "k",
    label: "V1",
    isLatest: true,
    ...(withSnapshot ? { snapshot: { snapshotId: "s1" } } : {}),
  }) as ViewItem;

const sources = (over: Partial<SurfaceDeps> = {}) =>
  createSurfaceSources({
    viewItems: () => [],
    tasks: () => [],
    plan: () => null,
    branch: () => null,
    subagents: () => [],
    ...over,
  });

describe("availability", () => {
  test("nothing is offered on a fresh thread", () => {
    const s = sources();
    expect(s.view.available()).toBe(false);
    expect(s.tasks.available()).toBe(false);
    expect(s.plan.available()).toBe(false);
    expect(s.diff.available()).toBe(false);
    expect(s.files.available()).toBe(false);
  });

  test("an empty task list is not a task list", () => {
    expect(sources({ tasks: () => [] }).tasks.available()).toBe(false);
    expect(
      sources({ tasks: () => [taskItem("do the thing")] }).tasks.available(),
    ).toBe(true);
  });

  test("the plan surface waits on a plan, which most threads never have", () => {
    expect(sources({ plan: () => null }).plan.available()).toBe(false);
    expect(sources({ plan: () => planDoc("pending") }).plan.available()).toBe(
      true,
    );
    // Still offered once answered: a plan the operator approved is what the thread is
    // working to, and taking it away the moment it was agreed would hide the reference
    // exactly when it starts being used.
    expect(sources({ plan: () => planDoc("approved") }).plan.available()).toBe(
      true,
    );
  });

  test("the diff waits on a branch, which most threads never have", () => {
    expect(sources({ branch: () => null }).diff.available()).toBe(false);
    expect(
      sources({
        branch: () => ({ branch: "x" }) as BranchState,
      }).diff.available(),
    ).toBe(true);
  });

  test("files need a captured snapshot, not merely a live head", () => {
    expect(
      sources({ viewItems: () => [viewItem(false)] }).files.available(),
    ).toBe(false);
    expect(
      sources({ viewItems: () => [viewItem(true)] }).files.available(),
    ).toBe(true);
    // The View itself is happy with either.
    expect(
      sources({ viewItems: () => [viewItem(false)] }).view.available(),
    ).toBe(true);
  });
});

describe("arrival", () => {
  test("a plan waiting on an answer puts itself on screen", () => {
    expect(sources({ plan: () => planDoc("pending") }).plan.arrival()).toBe(
      "steal",
    );
  });

  test("a plan that has been answered only announces", () => {
    // Approved, rejected, or being revised, it is a record rather than a question —
    // and a record has nobody waiting on it.
    for (const status of ["approved", "denied", "revising"] as PlanStatus[]) {
      expect(sources({ plan: () => planDoc(status) }).plan.arrival()).toBe(
        "announce",
      );
    }
  });

  test("no plan interrupts nobody", () => {
    expect(sources({ plan: () => null }).plan.arrival()).toBe("announce");
  });

  test("a plan resubmitted after feedback is a new arrival", () => {
    const first = sources({
      plan: () => planDoc("pending", 1),
    }).plan.claimKey();
    const second = sources({
      plan: () => planDoc("pending", 2),
    }).plan.claimKey();
    expect(first).not.toBe(second);
  });

  test("the same plan re-rendering is not", () => {
    expect(sources({ plan: () => planDoc("pending", 3) }).plan.claimKey()).toBe(
      sources({ plan: () => planDoc("pending", 3) }).plan.claimKey(),
    );
  });

  test("the task list never interrupts — the transcript already narrates it", () => {
    const s = sources({ tasks: () => [taskItem("a")] });
    expect(s.tasks.arrival()).toBe("announce");
    expect(s.tasks.claimKey()).toBe("");
  });

  test("the View opens once a thread, and the quiet surfaces stay quiet", () => {
    const s = sources();
    expect(s.view.arrival()).toBe("steal");
    // A constant key is what makes it once-per-thread rather than once-per-item.
    expect(s.view.claimKey()).toBe("");
    expect(s.diff.arrival()).toBe("announce");
    expect(s.files.arrival()).toBe("silent");
  });
});
