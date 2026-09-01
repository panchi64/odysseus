/**
 * Settling the calls a run parked on — the permissions it needs and the questions it
 * asked.
 *
 * A parked run is waiting on the operator, and it resumes only when one body covers
 * *every* call it stopped for — which is why nothing here submits one call at a time, and
 * why approvals and answers go in the same POST rather than in two. A turn can stop for
 * both reasons at once, and it resumes once; two submissions would mean the second
 * arriving at a run that had already moved on.
 *
 * Each surface (the dock over the composer, the host-command terminal) gathers its whole
 * set and posts it as a batch; the open stream carries the results back, and the
 * optimistic patch exists only so the dock clears on the click rather than a round trip
 * later.
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
import type {
  Approval,
  ApprovalDecision,
  ChatMessage,
  HostCommandBlock,
  QuestionAnswer,
  QuestionBlock,
} from "../model";
import type { PatchById } from "./patch";

export interface ApprovalDeps {
  messages: ChatMessage[];
  patchById: PatchById;
  /** Whether a turn is in flight — a park is by definition the live turn waiting. */
  sending: () => boolean;
  /** Reconcile with whatever the winning decision did, after this one lost the race. */
  reconcileStaleDecision: () => Promise<void>;
}

/** What the live turn is parked on, for the dock that takes over the composer. `null`
 *  when nothing is — which is what puts the composer back. */
export interface Park {
  /** The message the park belongs to; every submit is addressed to its run. */
  messageId: string;
  approvals: Approval[];
  questions: QuestionBlock["question"][];
  /** True once a submitted decision for this park 409'd. The dock stays up, inert and
   *  explained, until the refetch reconciles — putting the composer back on a 409 would
   *  suggest the run had moved on, which is exactly what nobody yet knows. */
  stale: boolean;
}

export interface ApprovalOps {
  /** True while the room has a live, unanswered park — an approval or a question. */
  awaitingInput: Accessor<boolean>;
  /** What the live turn is parked on, or `null`. The dock renders this. */
  park: Accessor<Park | null>;
  /** Settle everything a park is waiting on — decisions and answers in one call,
   *  because the run resumes on one body covering all of it. The dock clears once
   *  submitted. */
  resolvePark: (
    messageId: string,
    settlement: {
      decisions?: ApprovalDecision[];
      answers?: QuestionAnswer[];
    },
  ) => Promise<void>;
  /** Decide a message's host-command approvals. Approved commands begin running
   *  and denied ones close out optimistically; the stream confirms the outcome. */
  resolveHostCommands: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => Promise<void>;
}

export function createApprovalOps(deps: ApprovalDeps): ApprovalOps {
  // What the live turn stopped on, read straight off its blocks — folded there by
  // `approval.required` and `question.asked`. A derived memo rather than its own
  // set/clear pair: the blocks are already the single source of truth for "is something
  // still pending", and a flag kept beside them is the one that goes stale.
  //
  // Gated on `sending()` so it clears the moment the run stops being in flight, whether
  // by resolution (the block is filtered out of `messages` on submit — see
  // `resolvePark`), a cancel, or the run ending.
  //
  // Scoped to the turn in flight, and not out of tidiness: a park is by definition the
  // *live* turn waiting, since a turn cannot end with a call still undecided — so every
  // earlier turn in the transcript is a message × block walk that can only ever answer
  // no, re-run on every block the run pushes. A detached turn counts as live for the
  // same reason `sending` stays true through one: the run may still be parked
  // server-side.
  const park = createMemo<Park | null>(() => {
    if (!deps.sending()) return null;
    const live = deps.messages.findLast((m) => m.streaming || m.detached);
    if (!live) return null;
    const approvals: Approval[] = [];
    const questions: QuestionBlock["question"][] = [];
    for (const b of live.blocks ?? []) {
      if (b.kind === "approval") approvals.push(b.approval);
      else if (b.kind === "question") questions.push(b.question);
    }
    if (!approvals.length && !questions.length) return null;
    return {
      messageId: live.id,
      approvals,
      questions,
      // One flag for the park, not one per call: the whole batch resumes on one
      // submission, so a 409 stales all of it at once.
      stale: approvals.some((a) => a.stale) || questions.some((q) => q.stale),
    };
  });

  // The host-command terminal keeps its own pending phase on the rail — it is a running
  // terminal, not a prompt, and only its first moment is a decision. It still counts as
  // the run waiting on the operator.
  const awaitingInput = createMemo(() => {
    // A *stale* park doesn't need them: the run already resumed elsewhere, so the
    // attention echo should clear even though the dock stays up to say so.
    const p = park();
    if (p) return !p.stale;
    if (!deps.sending()) return false;
    const live = deps.messages.findLast((m) => m.streaming || m.detached);
    return (
      live?.blocks?.some(
        (b) => b.kind === "host_command" && b.command.phase === "pending",
      ) ?? false
    );
  });

  /** POST everything a message's parked run is waiting on, then apply an optimistic
   *  patch. The open run stream resumes with the results — the parked run requires a
   *  body covering *every* pending call, approvals and questions alike, which is why
   *  each surface batches its whole set into one POST. */
  async function submitDecisions(
    messageId: string,
    body: { decisions?: ApprovalDecision[]; answers?: QuestionAnswer[] },
    optimistic: (m: ChatMessage) => void,
  ): Promise<void> {
    const msg = deps.messages.find((m) => m.id === messageId);
    if (!msg?.runId) return;
    const decisions = body.decisions ?? [];
    try {
      await api.post(`/runs/${msg.runId}/approve`, {
        decisions,
        answers: body.answers ?? [],
      });
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
            else if (b.kind === "question") b.question.stale = true;
            else if (b.kind === "host_command" && b.command.phase === "pending")
              b.command.phase = "stale";
          }
        });
        toast.error("This was already answered elsewhere.");
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
    awaitingInput,
    park,
    resolvePark: (messageId, settlement) =>
      submitDecisions(messageId, settlement, (m) => {
        // Both kinds clear together, whichever the park held: one submission settled
        // the whole park, so leaving either behind would leave a dock up over a run
        // that has already resumed.
        if (m.blocks)
          m.blocks = m.blocks.filter(
            (b) => b.kind !== "approval" && b.kind !== "question",
          );
      }),
    resolveHostCommands: (messageId, decisions) =>
      submitDecisions(messageId, { decisions }, (m) => {
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
