/**
 * One SSE event, applied to the transcript.
 *
 * This is the whole of the live-to-store translation, and it is deliberately the only
 * thing in this file. The controller around it owns the *run* — opening the reader,
 * cancelling, reattaching, persisting — and none of that belongs in a switch whose single
 * question is "what does this frame change on screen". Splitting them means a new event
 * type is a case here and nothing else, and a change to how a run is driven never risks
 * touching how a delta lands.
 *
 * **Three invariants everything below depends on.**
 *
 * *Idempotence.* A reattach replays a run's buffer from an earlier seq, so events arrive
 * that were already applied — sometimes over a transcript that was cold-loaded with them
 * baked in. `seq` is monotonic per run, so the high-water mark drops the overlap; where a
 * frame can also arrive over a *persisted* row (the compaction divider, a snapshot chip, a
 * steering bubble) it is additionally deduped on its own durable id.
 *
 * *One fold target, which can move.* Events land on the assistant bubble the drive opened,
 * until a `message.injected` boundary closes it and opens a fresh one — mirroring how the
 * backend persists a steered turn as segments around the injected user message, so the
 * live transcript and a reload agree about the shape of the turn.
 *
 * *Conversation-scoped things are not message blocks.* A live browser session, the plan,
 * the snapshot list and the window meter outlive the run that announced them; folding them
 * onto a message would resurrect a long-reaped browser, or strand a plan on the turn that
 * happened to create it, the next time the transcript replays.
 */

import type { SetStoreFunction } from "solid-js/store";
import { produce } from "solid-js/store";
import type { ContextWindow, PlanItem, RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import {
  formatArgs,
  stringifyResult,
  toStats,
  toolImages,
  toTerminalOutcome,
  toVersionChipBlock,
  toViewSnapshotRef,
} from "../data/mappers";
import { refreshSessions } from "../data/sessions";
import { revealTitle } from "../data/titleReveals";
import type { ChatMessage, ConversationStats, ViewSnapshotRef } from "../model";
import { terminalResult } from "../toolPresentation";
import { describeToolArgs, describeToolResult } from "../toolSummary";
import {
  appendDelta,
  clearPark,
  findReview,
  findTool,
  nextId,
  upsertHost,
  type PatchById,
} from "./patch";

/** The run-scoped bookkeeping the fold both reads and advances. Shared by reference
 *  with the controller, which resets it on a thread switch and reads `maxFoldedSeq`
 *  as the resume point for a reattach — one object rather than a getter/setter pair
 *  per field, because these four are always read and reset together. */
export interface FoldState {
  /** The highest event `seq` folded for the current run. Two purposes: the resume
   *  point a reattach replays *after*, and the idempotency guard below. Events are
   *  seq ≥ 1, so 0 means nothing has been folded. */
  maxFoldedSeq: number;
  /** The assistant message events currently fold onto — normally the placeholder the
   *  drive was started with, until a `message.injected` boundary retargets it. */
  foldTarget: string | null;
  /** Bumped on every `plan.updated`. Plain counter, not a signal: its only job is to
   *  let an in-flight REST backfill notice the stream overtook it. */
  planRevision: number;
  /** The run currently streaming, if any — stamped onto a bubble this fold opens. */
  activeRunId: string | null;
}

/** Everything the fold is allowed to touch. Passed in rather than reached for, so the
 *  same fold serves the persistent main room and an ephemeral compare pane without
 *  either one knowing the other exists. */
export interface FoldDeps {
  state: FoldState;
  /** The controller's, not a second one: the index hint it keeps only pays off if
   *  every delta goes through the same instance. */
  patchById: PatchById;
  setMessages: SetStoreFunction<ChatMessage[]>;
  setSnapshots: (fn: (prev: ViewSnapshotRef[]) => ViewSnapshotRef[]) => void;
  setBrowserStream: (url: string | null) => void;
  setPlan: (items: PlanItem[]) => void;
  setUsage: (context: ContextWindow | null) => void;
  setStats: (stats: ConversationStats | null) => void;
  setErrored: (errored: boolean) => void;
}

export function createFolder(
  deps: FoldDeps,
): (anchorId: string, ev: RunEvent) => void {
  const { state, patchById, setMessages } = deps;

  return function foldEvent(anchorId: string, ev: RunEvent): void {
    // Idempotency: `seq` is monotonic per run, so an event at or below the high-
    // water mark was already folded (a reattach replay overlapping a still-live
    // reader). Skipping it stops a re-applied `answer.delta` from doubling text.
    if (ev.seq <= state.maxFoldedSeq) return;
    state.maxFoldedSeq = ev.seq;
    // Events land on the current fold target: the drive's placeholder until a
    // `message.injected` boundary retargets to a fresh assistant bubble.
    const assistantId = state.foldTarget ?? anchorId;
    switch (ev.type) {
      case "thinking.delta":
        patchById(assistantId, (m) => appendDelta(m, "thinking", ev.text));
        break;
      case "answer.delta":
        patchById(assistantId, (m) => appendDelta(m, "text", ev.text));
        break;
      case "tool.started":
        // A command the operator watches run is a terminal, not a generic tool card.
        // Which tools those are is the table's answer, not a name test here — see
        // `ToolEntry.terminal`. (tool.started fires before approval.required, so this
        // seeds the pending terminal.)
        if (terminalResult(ev.name)) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, ev.name, {
              command:
                typeof ev.args.command === "string" ? ev.args.command : "",
              explanation:
                typeof ev.args.explanation === "string"
                  ? ev.args.explanation
                  : undefined,
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "tool",
            id: `tool-${ev.tool_call_id}`,
            tool: {
              id: ev.tool_call_id,
              name: ev.name,
              args: formatArgs(ev.args),
              detail: describeToolArgs(ev.name, ev.args),
              status: "running",
            },
          });
        });
        break;
      case "tool.progress":
        // A running tool's status note (e.g. the sandbox spinning up). Folds onto
        // the generic tool card; a terminal has its own lifecycle and no block for
        // this to land on, so the lookup simply misses.
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) b.tool.progress = ev.partial ?? undefined;
        });
        break;
      case "tool.completed": {
        // A call with a result is waiting on nobody — retire the prompt it parked on,
        // so a replay doesn't re-ask what was already answered.
        patchById(assistantId, (m) => clearPark(m, ev.tool_call_id));
        const terminal = terminalResult(ev.name);
        if (terminal) {
          // The two terminal tools report differently — a record from the sandboxed
          // one, a labelled string from the worktree shell — and `toTerminalOutcome`
          // is where that difference is resolved.
          const outcome = toTerminalOutcome(terminal, ev.result);
          if (outcome)
            patchById(assistantId, (m) =>
              upsertHost(m, ev.tool_call_id, ev.name, outcome),
            );
          break;
        }
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) {
            b.tool.status = "ok";
            b.tool.result = stringifyResult(ev.result);
            b.tool.outcome = describeToolResult(ev.name, ev.result);
            b.tool.progress = undefined; // the run is over — drop the spin-up note
            b.tool.images = toolImages(ev.images);
          }
        });
        break;
      }
      case "tool.failed":
        // A failure settles the call too — same retirement as the completed case.
        patchById(assistantId, (m) => clearPark(m, ev.tool_call_id));
        if (terminalResult(ev.name)) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, ev.name, {
              phase: "error",
              error: ev.error,
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          const b = findTool(m, ev.tool_call_id);
          if (b) {
            b.tool.status = "error";
            b.tool.error = ev.error;
            b.tool.progress = undefined; // the run is over — drop the spin-up note
          }
        });
        break;
      case "context.injected":
        // A block the chassis put in front of the model. It lands on the rail in the
        // order it happened — which is ahead of the work it shaped, since the turn's
        // context is assembled before the model sees any of it. Keyed by `seq` because
        // the same contributor can legitimately inject twice in one turn (a plan that
        // grew a task between steps is a new injection, not a repeat), and `seq` is the
        // only identifier on the wire that is unique per event and stable across a
        // replay.
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "context",
            id: `ctx-${ev.seq}`,
            injection: {
              contributor: ev.contributor,
              placement: ev.placement,
              tokens: ev.tokens,
              text: ev.text,
              truncated: ev.truncated,
            },
          });
        });
        break;
      case "review.started":
        // The chassis is about to answer for the operator. The row opens now rather than
        // on the verdict, so a review that costs a model call reads as work in flight —
        // and so it lands ahead of the tool row it judges, which is where it belongs.
        patchById(assistantId, (m) => {
          if (findReview(m, ev.tool_call_id)) return;
          (m.blocks ?? (m.blocks = [])).push({
            kind: "review",
            id: `review-${ev.tool_call_id}`,
            review: {
              toolCallId: ev.tool_call_id,
              name: ev.name,
              summary: ev.summary,
            },
          });
        });
        break;
      case "review.completed":
        patchById(assistantId, (m) => {
          const b = findReview(m, ev.tool_call_id);
          if (!b) return;
          b.review.decision = ev.decision;
          b.review.stage = ev.stage;
          b.review.reason = ev.reason;
          // Null on the wire means the model stage never ran — the deterministic judge
          // cleared it, or there was nothing to review with. Undefined here so the card
          // renders the axes only when there are axes.
          b.review.risk = ev.risk ?? undefined;
          b.review.authorization = ev.authorization ?? undefined;
          b.review.correctness = ev.correctness ?? undefined;
        });
        break;
      case "plan.updated":
        // Whole-list replace, not a merge: the event is full state, which is what makes
        // it idempotent when the stream is replayed from an earlier seq on reconnect.
        state.planRevision += 1;
        deps.setPlan(ev.items);
        break;
      case "approval.required": {
        // `args` is typed as always-present, but it arrives as untrusted JSON off
        // the wire — default it once here, in the mapper, so no consumer of the
        // stored block has to guard a `Object.keys(args)` or an `args.command`.
        const args: Record<string, unknown> = ev.args ?? {};
        if (terminalResult(ev.name)) {
          patchById(assistantId, (m) =>
            upsertHost(m, ev.tool_call_id, ev.name, {
              command: typeof args.command === "string" ? args.command : "",
              explanation: ev.explanation ?? undefined,
              phase: "pending",
            }),
          );
          break;
        }
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "approval",
            id: `approval-${ev.tool_call_id}`,
            approval: {
              toolCallId: ev.tool_call_id,
              name: ev.name,
              args,
              summary: ev.summary,
              explanation: ev.explanation ?? undefined,
            },
          });
        });
        break;
      }
      case "question.asked": {
        // Same defaulting discipline as `approval.required` above: `questions` is typed
        // as always-present but arrives as untrusted JSON, so it is defaulted once here
        // rather than guarded at every consumer of the stored block.
        patchById(assistantId, (m) => {
          (m.blocks ?? (m.blocks = [])).push({
            kind: "question",
            id: `question-${ev.tool_call_id}`,
            question: {
              toolCallId: ev.tool_call_id,
              questions: (ev.questions ?? []).map((q) => ({
                question: q.question,
                multiSelect: q.multi_select ?? false,
                options: (q.options ?? []).map((o) => ({
                  label: o.label,
                  description: o.description ?? undefined,
                })),
              })),
            },
          });
        });
        break;
      }
      case "view.live": {
        // One live head per *conversation*, not per turn: clear any prior live
        // block (it may sit on an earlier turn) before marking this turn's, so a
        // replaced or stopped server never lingers as a stale LIVE head once the
        // viewport aggregates view items across the whole transcript.
        const live = { url: ev.url, title: ev.title ?? undefined };
        setMessages(
          produce((list) => {
            for (const m of list)
              if (m.blocks)
                m.blocks = m.blocks.filter((b) => b.kind !== "view_live");
            const m = list.find((x) => x.id === assistantId);
            if (m)
              (m.blocks ?? (m.blocks = [])).push({
                kind: "view_live",
                id: nextId("view-live"),
                live,
              });
          }),
        );
        break;
      }
      case "view.live.stopped":
        // The live head is conversation-scoped and close usually arrives a turn or
        // more after it started — drop it wherever it lives, not just on this run.
        setMessages(
          produce((list) => {
            for (const m of list)
              if (m.blocks)
                m.blocks = m.blocks.filter((b) => b.kind !== "view_live");
          }),
        );
        break;
      case "browser.live":
        // Conversation-scoped, not a message block: the session outlives this run, and a
        // block would replay a long-reaped browser on the next cold load. There is no
        // stopped counterpart — the panel's own socket carries the end (see
        // `browserLive.ts`), because a reap happens between turns with no stream to
        // carry an event.
        deps.setBrowserStream(ev.url);
        break;
      case "view.snapshot": {
        // A version minted by `show`: append to the conversation-scoped version list
        // (the panel), deduped since a reattach replay can re-deliver the event.
        const ref = toViewSnapshotRef(ev);
        deps.setSnapshots((prev) =>
          prev.some((s) => s.snapshotId === ref.snapshotId)
            ? prev
            : [...prev, ref],
        );
        // Fold an inline transcript chip only for a *static* preview (a `show(file=…)`).
        // A live/auto version (served head) is already marked by its `view_live` chip,
        // so a second chip for the same action would just be visual duplication.
        if (ref.preview) {
          const chip = toVersionChipBlock(assistantId, {
            snapshotId: ref.snapshotId,
            title: ref.title,
            previewKind: ref.preview.kind,
          });
          patchById(assistantId, (m) => {
            const blocks = m.blocks ?? (m.blocks = []);
            if (!blocks.some((b) => b.id === chip.id)) blocks.push(chip);
          });
        }
        break;
      }
      case "message.queued":
        // A steering message the backend accepted into this run. Usually it tags
        // the optimistic bubble `send` already pushed (matched by text, first
        // untagged wins so duplicate texts pair off in order); on a reattach
        // replay there is no optimistic bubble, so rebuild it from the event.
        setMessages(
          produce((list) => {
            if (list.some((m) => m.queuedMessageId === ev.message_id)) return;
            const untagged = list.find(
              (m) =>
                m.queuedPending && !m.queuedMessageId && m.content === ev.text,
            );
            if (untagged) untagged.queuedMessageId = ev.message_id;
            else
              list.push({
                id: nextId("u"),
                role: "user",
                content: ev.text,
                queuedPending: true,
                queuedMessageId: ev.message_id,
                createdAt: ev.ts,
              });
          }),
        );
        break;
      case "message.edited":
        // The operator rewrote a still-pending bubble. Usually `editQueued`
        // already applied the text optimistically-on-success; this fold makes a
        // reattach replay (and any second tab) converge on the same content. An
        // already-injected message is part of the turn and never changes.
        setMessages(
          produce((list) => {
            const bubble = list.find(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (bubble) bubble.content = ev.text;
          }),
        );
        break;
      case "message.withdrawn":
        // Only a still-pending bubble is removable — an already-injected message
        // is part of the turn and must never vanish from the transcript.
        setMessages(
          produce((list) => {
            const i = list.findIndex(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (i >= 0) list.splice(i, 1);
          }),
        );
        break;
      case "message.injected":
        // The queued message reached the model: promote its bubble to a normal
        // user turn and split the assistant flow around it, mirroring how the
        // backend persists the steered turn (…assistant segment, user message,
        // next assistant segment…) so the live transcript and a reload agree.
        setMessages(
          produce((list) => {
            const qi = list.findIndex(
              (m) => m.queuedMessageId === ev.message_id && m.queuedPending,
            );
            if (qi < 0) return;
            const [bubble] = list.splice(qi, 1);
            bubble.queuedPending = false;
            const target = list.find((m) => m.id === assistantId);
            const targetIsFresh =
              target && !target.blocks?.length && !target.content;
            if (targetIsFresh && list[list.length - 1] === target) {
              // A batch of injections at one boundary shares one fresh segment:
              // slot this message before the placeholder a prior injection opened.
              list.splice(list.length - 1, 0, bubble);
            } else {
              if (target) target.streaming = false;
              list.push(bubble);
              const fresh: ChatMessage = {
                id: nextId("a"),
                role: "assistant",
                model: target?.model,
                content: "",
                blocks: [],
                streaming: true,
                runId: state.activeRunId ?? undefined,
                createdAt: new Date().toISOString(),
              };
              list.push(fresh);
              state.foldTarget = fresh.id;
            }
          }),
        );
        break;
      case "conversation.compacted": {
        // Conversation-level, like the title above — but it *is* a message, so it goes
        // into the list. Placed after the turn the backend named rather than appended:
        // a divider at the bottom would claim to have folded the turns it kept, and a
        // reload (which places it chronologically) would then disagree with the live view.
        const divider: ChatMessage = {
          id: ev.message_id,
          role: "compaction",
          content: ev.summary,
          createdAt: ev.ts,
          foldedMessages: ev.messages_compacted,
          tokensBefore: ev.tokens_before ?? undefined,
          tokensAfter: ev.tokens_after ?? undefined,
        };
        // Idempotent on `message_id`: a reattach replays the run's whole buffer
        // (`fromSeq: 0`) over a transcript that was cold-loaded *with* this divider
        // already in it, so an unguarded splice would seat a second identical rule —
        // and re-announce a fold that happened minutes ago.
        let inserted = false;
        setMessages(
          produce((list) => {
            if (list.some((m) => m.id === divider.id)) return;
            inserted = true;
            const at = ev.after_message_id
              ? list.findIndex((m) => m.id === ev.after_message_id)
              : -1;
            if (at >= 0) list.splice(at + 1, 0, divider);
            else list.push(divider);
          }),
        );
        // A fold that lands mid-answer scrolls past unseen — and it changes what the
        // model can still see, which is not something to discover later by reading
        // back. The divider is the durable record; this is the notification.
        // `messages_compacted` counts messages, not exchanges — say messages.
        if (inserted)
          toast.info(
            ev.messages_compacted > 0
              ? `Context compacted — ${ev.messages_compacted} earlier ${ev.messages_compacted === 1 ? "message is" : "messages are"} now a summary for the model.`
              : "Context compacted — earlier messages are now a summary for the model.",
          );
        break;
      }
      case "conversation.titled":
        // Conversation-level, not message-level: hand it to the typewriter reveal
        // rather than folding onto the assistant message. The throbber clears in the
        // run's `finally` (when the new conversation's id is adopted and the reveal
        // can actually render), not here — clearing now would flash the bare title
        // for the beat before that.
        revealTitle(ev.conversation_id, ev.title);
        break;
      case "conversation.linked":
        // The turn spawned a thread of its own. Pull the list now rather than at
        // the end of the turn: the new thread is already running, and a session
        // that exists but isn't listed for another few minutes reads as work that
        // went nowhere. The toast is the account of *why* a row appeared.
        refreshSessions();
        toast.info(
          ev.title
            ? `Research thread started — ${ev.title}`
            : "Research thread started.",
        );
        break;
      case "run.error":
        toast.error(ev.message || "The run failed.");
        patchById(assistantId, (m) => (m.streaming = false));
        deps.setErrored(true);
        break;
      case "run.metrics":
        // The backend derives the window's fullness; the meter just renders it.
        // Authoritative either way: a null context (this turn ran on a windowless
        // model, or reported no usage) clears a stale reading rather than keeping it.
        deps.setUsage(ev.context);
        deps.setStats(toStats(ev));
        break;
      case "citation.added":
        patchById(assistantId, (m) => {
          const citations = m.citations ?? (m.citations = []);
          if (!citations.some((c) => c.url === ev.url))
            citations.push({ url: ev.url, title: ev.title ?? undefined });
        });
        break;
      case "limit.notice":
        // A bound on the turn. "verify" is a transient "re-attempting…" progress note,
        // not a stop — leave it silent. The rest stopped the run, so surface why: the
        // "context" message carries the model's window size, so the operator knows the
        // conversation hit the ceiling and can start a new chat rather than wonder.
        if (ev.limit !== "verify") toast.error(ev.message);
        break;
      case "run.ended":
        // A blocked outcome is a real stopping point, not a normal finish —
        // leave a persistent marker on the turn (the limit.notice toast alone
        // vanishes, and a reload would otherwise show a turn that just stops).
        if (ev.outcome === "blocked")
          patchById(assistantId, (m) => {
            m.blocked = true;
            m.blockedDetail = ev.detail ?? undefined;
          });
        break;
      // run.started / step.*: no store change
    }
  };
}
