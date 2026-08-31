/**
 * Deciding the calls a run parked on.
 *
 * A parked run is waiting on the operator, and it resumes only when a decision covers
 * *every* call it stopped for — which is why nothing here submits one decision at a time.
 * Each surface (the approval card, the host-command terminal) gathers its whole set and
 * posts it as a batch; the open stream carries the results back, and the optimistic patch
 * exists only so the cards clear on the click rather than a round trip later.
 *
 * **A decision can be lost, and losing one is not a failure to retry.** The same run can
 * be decided from a second tab, or by a retried request that lands after the run has
 * already resumed — the backend answers 409, and resubmitting would 409 forever. So a
 * lost race marks the cards *stale* (visible, inert, explained) and refetches the thread,
 * while an ordinary transport failure leaves them interactive. Those two error paths
 * looking alike is exactly what makes them worth stating apart.
 *
 * **Whether anything is parked is read off the blocks, not tracked beside them.** The
 * transcript already knows; a second flag kept in step with it would be a second answer to
 * the same question, and the one that goes stale is always the flag.
 */

import { createMemo, type Accessor } from "solid-js";
import { api, isApiError } from "~/lib/api";
import { toast } from "~/ui";
import { bumpGrantsRevision } from "../data/conversations";
import type { ApprovalDecision, ChatMessage, HostCommandBlock } from "../model";
import type { PatchById } from "./patch";

export interface ApprovalDeps {
  messages: ChatMessage[];
  patchById: PatchById;
  /** Whether a turn is in flight — a park is by definition the live turn waiting. */
  sending: () => boolean;
  /** Reconcile with whatever the winning decision did, after this one lost the race. */
  reconcileStaleDecision: () => Promise<void>;
}

export interface ApprovalOps {
  /** True while the room has a live, undecided approval. */
  awaitingApproval: Accessor<boolean>;
  /** Decide a message's pending approvals; the cards clear once submitted. */
  resolveApproval: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => Promise<void>;
  /** Decide a message's host-command approvals. Approved commands begin running
   *  and denied ones close out optimistically; the stream confirms the outcome. */
  resolveHostCommands: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => Promise<void>;
}

export function createApprovalOps(deps: ApprovalDeps): ApprovalOps {
  // Folded by `approval.required` (both the generic approval card and the host-command
  // terminal's pending phase) and gated on `sending()` so it clears the moment the run
  // stops being in flight, whether by resolution (the approval/host-command block is
  // filtered/re-phased out of `messages` on submit — see `resolveApproval`/
  // `resolveHostCommands`), a cancel, or the run ending. A derived memo rather than its
  // own set/clear pair: the blocks are already the single source of truth for "is
  // something still pending", so this only reads them.
  //
  // Scoped to the turn in flight, and not out of tidiness: a park is by definition the
  // *live* turn waiting, since a turn cannot end with a call still undecided — so every
  // earlier turn in the transcript is a message × block walk that can only ever answer
  // no, re-run on every block the run pushes. A detached turn counts as live for the
  // same reason `sending` stays true through one: the run may still be parked
  // server-side.
  const awaitingApproval = createMemo(() => {
    if (!deps.sending()) return false;
    const live = deps.messages.findLast((m) => m.streaming || m.detached);
    return (
      live?.blocks?.some(
        (b) =>
          (b.kind === "approval" && !b.approval.stale) ||
          (b.kind === "host_command" && b.command.phase === "pending"),
      ) ?? false
    );
  });

  /** POST a batch of approval decisions for a message's run, then apply an
   *  optimistic patch. The open run stream resumes with the results — the parked
   *  run requires a decision covering *every* pending call, which is why each
   *  surface batches its decisions into one POST. */
  async function submitDecisions(
    messageId: string,
    decisions: ApprovalDecision[],
    optimistic: (m: ChatMessage) => void,
  ): Promise<void> {
    const msg = deps.messages.find((m) => m.id === messageId);
    if (!msg?.runId) return;
    try {
      await api.post(`/runs/${msg.runId}/approve`, { decisions });
      deps.patchById(messageId, optimistic);
      // A recorded conversation grant must show on the strip now, not on the next
      // stream toggle — nudge the grants resource to refetch.
      if (decisions.some((d) => d.scope === "conversation")) {
        bumpGrantsRevision();
      }
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        // The decision was already made elsewhere (a second tab, a retried
        // request that landed after the run resumed) — resubmitting would just
        // 409 forever. Mark the pending cards stale (non-interactive, with a
        // note) instead of leaving them re-clickable, then refetch so the
        // transcript catches up to whatever actually happened.
        deps.patchById(messageId, (m) => {
          for (const b of m.blocks ?? []) {
            if (b.kind === "approval") b.approval.stale = true;
            else if (b.kind === "host_command" && b.command.phase === "pending")
              b.command.phase = "stale";
          }
        });
        toast.error("This decision was already made elsewhere.");
        void deps.reconcileStaleDecision();
        return;
      }
      // A transient failure (network blip, 5xx): the decision may not have
      // landed at all, so keep the card interactive and let the operator retry.
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to submit the decision.",
      );
    }
  }

  return {
    awaitingApproval,
    resolveApproval: (messageId, decisions) =>
      submitDecisions(messageId, decisions, (m) => {
        if (m.blocks) m.blocks = m.blocks.filter((b) => b.kind !== "approval");
      }),
    resolveHostCommands: (messageId, decisions) =>
      submitDecisions(messageId, decisions, (m) => {
        for (const d of decisions) {
          const b = m.blocks?.find(
            (x): x is HostCommandBlock =>
              x.kind === "host_command" &&
              x.command.toolCallId === d.tool_call_id,
          );
          if (b) b.command.phase = d.approved ? "running" : "denied";
        }
      }),
  };
}
