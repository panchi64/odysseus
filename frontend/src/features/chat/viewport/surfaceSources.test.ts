/** What each surface has, and whether it may interrupt.
 *
 *  Availability is the cheap half and still worth pinning: it decides which header
 *  buttons exist, so a source that answers wrongly either hides a surface the operator
 *  has content for or offers one that opens onto nothing.
 *
 *  **Arrival is the half with a judgement in it.** The rule the operator asked for is
 *  that a plan puts itself on screen when it is waiting on their approval and otherwise
 *  only badges — which means the answer depends on the thread's permission level, not on
 *  what kind of surface a plan is. That is the whole reason arrival is a predicate, and
 *  these are the cases that would make a static field wrong.
 */

import { describe, expect, test } from "bun:test";
import { createSurfaceSources, type SurfaceDeps } from "./surfaceSources";
import type { PermissionLevel } from "../model";
import type { PlanItem } from "~/lib/stream/events";
import type { BranchState } from "../data";
import type { ViewItem } from "./viewItems";

const planItem = (content: string): PlanItem => ({
  id: content,
  content,
  status: "pending",
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
    plan: () => [],
    branch: () => null,
    permission: () => "edit" as PermissionLevel,
    ...over,
  });

describe("availability", () => {
  test("nothing is offered on a fresh thread", () => {
    const s = sources();
    expect(s.view.available()).toBe(false);
    expect(s.plan.available()).toBe(false);
    expect(s.diff.available()).toBe(false);
    expect(s.files.available()).toBe(false);
  });

  test("an empty task list is not a plan", () => {
    expect(sources({ plan: () => [] }).plan.available()).toBe(false);
    expect(
      sources({ plan: () => [planItem("do the thing")] }).plan.available(),
    ).toBe(true);
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
  const awaiting = {
    plan: () => [planItem("a"), planItem("b")],
    permission: () => "plan" as PermissionLevel,
  };

  test("a plan waiting on approval puts itself on screen", () => {
    expect(sources(awaiting).plan.arrival()).toBe("steal");
  });

  test("the same plan on a thread that can act only announces", () => {
    for (const level of ["manual", "edit", "auto"] as PermissionLevel[]) {
      expect(
        sources({ ...awaiting, permission: () => level }).plan.arrival(),
      ).toBe("announce");
    }
  });

  test("plan level with no plan yet interrupts nobody", () => {
    expect(
      sources({ plan: () => [], permission: () => "plan" }).plan.arrival(),
    ).toBe("announce");
  });

  test("a revised plan still awaiting a yes is a new arrival", () => {
    const two = sources(awaiting).plan.claimKey();
    const three = sources({
      ...awaiting,
      plan: () => [planItem("a"), planItem("b"), planItem("c")],
    }).plan.claimKey();
    expect(two).not.toBe(three);
  });

  test("the same plan re-rendering is not", () => {
    expect(sources(awaiting).plan.claimKey()).toBe(
      sources(awaiting).plan.claimKey(),
    );
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
