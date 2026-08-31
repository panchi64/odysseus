/**
 * The thread controller — one conversation's live state, and the ops the room drives it
 * with.
 *
 * What is left here after the split is the *assembly*: the signals a thread's UI reads,
 * the ops that start and stop a turn, and the wiring that lets six single-purpose modules
 * behave as one object. Each of those modules answers a question this file deliberately no
 * longer does — driving a run's transport (`drive.ts`), what a frame changes on screen
 * (`fold.ts`), a message sent into a run already going (`steering.ts`), deciding the calls
 * a run parked on (`approvals.ts`), reconciling with what was persisted (`resume.ts`),
 * acting on a turn already recorded (`branching.ts`), and being pointed at a different
 * thread (`binding.ts`).
 *
 * **The optimistic store is authoritative for the thread it is on.** A turn's messages are
 * persisted only when it finishes, so a refetch mid-stream reads an empty conversation.
 * That rule is why `binding.ts` refuses to re-seed a live thread and why `resume.ts` adopts
 * ids rather than reseating wholesale.
 *
 * **The ops form a cycle, and it is a real one.** A run's teardown reconciles the thread,
 * reconciling can discover a live run and start a drive, and a drive hands undelivered
 * steering text back. Two of the wirings below therefore reach the drive at *call* time
 * rather than holding its handle, which is what makes the cycle two named edges instead of
 * one closure in which every part can reach every other.
 */

import { createEffect, createSignal } from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api, isApiError } from "~/lib/api";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import type { PlanItem } from "~/lib/stream";
import type { SessionMode } from "~/lib/modes";
import { toast } from "~/ui";
import { CONTINUE_PROMPT } from "../data/constants";
import type { ChatCreatedDTO, ConversationDetailDTO } from "../data/wire";
import type {
  ActiveRun,
  ChatMessage,
  ContextUsage,
  ConversationStats,
  PermissionLevel,
  ViewSnapshotRef,
} from "../model";
import { createApprovalOps } from "./approvals";
import { createThreadBinding } from "./binding";
import {
  createBranchingOps,
  reseatFromDetail,
  type TranscriptStore,
} from "./branching";
import { createRunDrive } from "./drive";
import { createFolder, type FoldState } from "./fold";
import { createPatchById, nextId } from "./patch";
import { createResumeOps } from "./resume";
import { createSteeringOps } from "./steering";

export interface ChatStreamOptions {
  /** Fired once when a brand-new conversation receives its backend id. */
  onConversationStarted?: (id: string) => void;
  /** Fired when a turn finishes (done or errored) — refresh the session list. */
  onTurnComplete?: () => void;
  /** Override the model this stream's turns run on, instead of the global picker
   *  selection. Used by the compare panes, which each own a per-pane model. */
  selection?: () => ModelSelection | null;
  /** Mark a freshly-created conversation as scratch (hidden from the sidebar
   *  listing). Used by compare panes — throwaway threads, not saved history. */
  ephemeral?: boolean;
  /** What kind of thread the *next new* conversation should be — an ordinary one, a
   *  research thread, or a code thread working in `projectId`'s git worktree. Read
   *  only when a send creates the conversation — the binding is immutable afterwards,
   *  and the backend owns it from then on. */
  mode?: () => SessionMode;
  projectId?: () => string | undefined;
  /** How far the model may go this turn — and from this turn onwards. Unlike the
   *  mode, sent on **every** send: the level is the operator's live control, so
   *  switching it mid-thread is a plain message rather than a separate call, and the
   *  backend persists whatever the last send named. */
  permission?: () => PermissionLevel;
  /** The loaded conversation's context-window state, seeded alongside its history
   *  so an existing thread shows window fullness before its next turn runs. */
  initialContext?: () => ContextUsage | null | undefined;
  /** The loaded conversation's cumulative readout, seeded the same way. The backend
   *  rebuilds it from the stored messages, so the line under the composer says the
   *  same thing after a reload as it did while the thread was live. */
  initialStats?: () => ConversationStats | null | undefined;
  /** The loaded conversation's in-flight run, if a turn is still streaming
   *  server-side. Seeds a reattach on a cold read (e.g. a page reload mid-stream)
   *  so the live answer continues instead of the thread rendering reply-less. */
  activeRun?: () => ActiveRun | null | undefined;
  /** The loaded conversation's workspace snapshots (git-style history), seeded
   *  alongside its messages so the viewport shows them before the next turn. */
  initialSnapshots?: () => ViewSnapshotRef[] | undefined;
}

export function createChatStream(
  initial: () => ChatMessage[] | undefined,
  key: () => string | null = () => null,
  options: ChatStreamOptions = {},
) {
  const [messages, setMessages] = createStore<ChatMessage[]>([]);
  // Conversation-level workspace snapshots (git-style history). Unlike versions/
  // live (which fold onto message blocks), snapshots are conversation-scoped, so
  // they live here beside the messages rather than in the transcript.
  const [snapshots, setSnapshots] = createSignal<ViewSnapshotRef[]>([]);
  // The thread's live agent browser, as a stream path — conversation-scoped like the
  // snapshots, and for a stronger reason: the browser session outlives the run that
  // opened it, so a message block (which replays with the transcript) would resurrect a
  // browser that has since been reaped.
  const [browserStream, setBrowserStream] = createSignal<string | null>(null);
  const [sending, setSending] = createSignal(false);
  // True when this room's last run ended in `run.error`; cleared when the next run
  // starts (in the drive). The main room mirrors it to the global `runErrored` echo
  // so the favicon can flag a failed run — compare panes keep it local.
  const [errored, setErrored] = createSignal(false);
  // A brand-new thread is auto-named during its first turn; this drives a "working"
  // throbber on the title from that turn's start until the name lands
  // (`conversation.titled`, which the reveal then animates) or the turn ends without
  // one. Backend-owned outcome — the frontend only reflects the in-flight window.
  const [titlePending, setTitlePending] = createSignal(false);
  // The latest run's context-window state, as derived by the backend. Null until
  // a run reports it against a known window (loaded history carries none), which
  // is when the context meter first appears.
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  // What the thread has cost — the composer's readout line. One signal, because the
  // backend sends one shape: the live `run.metrics` frame and the conversation load's
  // `stats` are the same payload, so a reload continues the same numbers rather than
  // blanking them. (This was three signals off one event; the counts and the token
  // counts were never separate facts.)
  const [stats, setStats] = createSignal<ConversationStats | null>(null);
  // The agent's task list for this thread. Conversation-level rather than a message
  // block: one list belongs to the thread and is rewritten in place as work proceeds,
  // so pinning it to the turn that happened to create it would strand it. `plan.updated`
  // carries the whole list, so applying an event is a replace, never a merge.
  const [plan, setPlan] = createSignal<PlanItem[]>([]);
  // The run-scoped bookkeeping the fold advances and the drive resets: the high-water
  // seq, the bubble events land on, the plan's revision counter, and the run currently
  // streaming. One object, shared by reference with the folder.
  const foldState: FoldState = {
    maxFoldedSeq: 0,
    foldTarget: null,
    planRevision: 0,
    activeRunId: null,
  };
  // The last run a cold-read reattach was kicked off for, so the load effect fires
  // at most once per run even if the session resource re-emits the same value.
  let reattachedRunId: string | null = null;
  // Set when the operator cancels the in-flight run, so the just-ended drive's
  // `adoptServerMeta` skips its reseat: a cancelled turn persists nothing, so the
  // backend history is *shorter* than the optimistic store, and reseating to it
  // would discard the whole in-flight turn (and, on a brand-new conversation with
  // no prior turns, blank the chat entirely). Reset at the start of each drive.
  let cancelled = false;
  // The conversation this stream is currently bound to (tracked separately from
  // the screen's `key`, which only updates once a new thread is persisted).
  let activeConversationId: string | null = key();

  const store: TranscriptStore = { setMessages, setUsage, setSnapshots };
  const reseat = (detail: ConversationDetailDTO) =>
    reseatFromDetail(store, detail);

  const patchById = createPatchById(messages, setMessages);

  const foldEvent = createFolder({
    state: foldState,
    patchById,
    setMessages,
    setSnapshots,
    setBrowserStream,
    setPlan,
    setUsage,
    setStats,
    setErrored,
  });

  // Steering: a message sent into a run that is already going, and the text handed
  // back when one never reached the model. It reaches the drive declared below
  // through a call-time closure rather than a handle — the cycle is real (a queue
  // attempt can turn into a fresh turn to drive, and a drive's teardown hands back
  // what it never delivered), and naming the edge is better than merging the two.
  const steering = createSteeringOps({
    messages,
    setMessages,
    patchById,
    conversationId: () => activeConversationId,
    adoptConversationId: (id) => {
      activeConversationId = id;
    },
    activeRunId: () => foldState.activeRunId,
    setSending,
    selection: () => options.selection?.() ?? effectiveSelection(),
    driveRun: (runId, assistantId) => drive.driveRun(runId, assistantId),
  });

  // Everything that reconciles the optimistic store with what the backend persisted.
  // It lives next door because all four are one move — read the detail, act on it only
  // if the operator is still on that thread — and that guard belongs in one place.
  // Same call-time edge to the drive, for the same reason: reconciling can discover a
  // run that is still live and hand it straight back to be driven.
  const resume = createResumeOps({
    conversationId: () => activeConversationId,
    fetchDetail: (id) => api.get<ConversationDetailDTO>(`/conversations/${id}`),
    messages,
    setMessages,
    reseat,
    reattachRun: (runId, opts) => drive.reattachRun(runId, opts),
    wasCancelled: () => cancelled,
  });

  const drive = createRunDrive({
    messages,
    setMessages,
    patchById,
    state: foldState,
    foldEvent,
    setSending,
    setErrored,
    setTitlePending,
    clearCancelled: () => {
      cancelled = false;
    },
    restoreUndelivered: steering.restoreUndelivered,
    conversationId: () => activeConversationId,
    adoptServerMeta: resume.adoptServerMeta,
    recoverLostRun: resume.recoverLostRun,
    onConversationStarted: (id) => options.onConversationStarted?.(id),
    onTurnComplete: () => options.onTurnComplete?.(),
  });

  // Deciding the calls a run parked on, and whether anything is still parked.
  const approvals = createApprovalOps({
    messages,
    patchById,
    sending,
    reconcileStaleDecision: () => resume.reconcileStaleDecision(),
  });

  // Re-seed when the conversation changes, and never over a live one.
  createThreadBinding({
    key,
    initial,
    messages,
    boundTo: () => activeConversationId,
    onBind: (id) => {
      // Forget which run we've already reattached-to: leaving this thread (still
      // detached/mid-stream) and returning later must let the cold-reattach effect
      // fire again for the same run id, rather than permanently ignoring a run it
      // saw once, in some earlier visit, before this stream instance existed.
      reattachedRunId = null;
      activeConversationId = id;
    },
    supersede: drive.supersede,
    setSending,
    state: foldState,
    setMessages,
    setUsage,
    setStats,
    setSnapshots,
    setBrowserStream,
    browserStream,
    setPlan,
    initialContext: options.initialContext,
    initialStats: options.initialStats,
    initialSnapshots: options.initialSnapshots,
  });

  async function send(
    text: string,
    attachmentIds: string[] = [],
    /** Set only by `continueTurn`: the branch node id of the stopped turn this
     *  send resumes, so the backend retires that turn's stop marker for good. */
    continuesMessageId?: string,
  ): Promise<void> {
    // A turn needs either prompt text or at least one attachment to send.
    if (!text.trim() && attachmentIds.length === 0) return;
    if (sending()) {
      // Mid-run steering is text-only — an attachment can't ride an existing
      // run's request (and the composer disables attach while streaming).
      if (attachmentIds.length > 0) {
        toast.error(
          "Attachments can't be added while a response is in progress.",
        );
        return;
      }
      if (!text.trim()) return;
      await steering.sendWhileStreaming(text);
      return;
    }
    setSending(true);

    const wasNew = activeConversationId === null;
    // A fresh, non-ephemeral thread gets auto-named during this turn; show the
    // working throbber on the title until it lands. Ephemeral threads aren't titled.
    if (wasNew && !options.ephemeral) setTitlePending(true);
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
      attachmentIds: attachmentIds.length ? attachmentIds : undefined,
    };
    // `override` is a genuine per-instance model (the compare panes); the default
    // path sends none, so the backend resolves the stored `main` binding — the same
    // source research/tasks/titling resolve. `selection` is only the display label.
    const override = options.selection?.();
    const selection = override ?? effectiveSelection();
    const assistantId = nextId("a");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      model: selection?.model,
      content: "",
      blocks: [],
      streaming: true,
      queued: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(produce((m) => m.push(userMsg, assistantMsg)));

    let created: ChatCreatedDTO;
    try {
      created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId ?? undefined,
        endpoint_id: override?.endpointId,
        model: override?.model,
        attachment_ids: attachmentIds,
        // Only meaningful when this turn creates the conversation; the backend
        // ignores it when continuing one.
        ephemeral: wasNew && options.ephemeral ? true : undefined,
        // Likewise: a thread's mode and project are set once, at creation. The
        // backend re-reads them off the conversation for every later turn, so
        // sending them again would be a second source for one fact.
        mode: wasNew ? options.mode?.() : undefined,
        project_id: wasNew ? options.projectId?.() : undefined,
        // The level, on the other hand, is sent every time: it is the one binding
        // fact that moves, and the composer's control moves it by being read here on
        // the next send rather than by a write of its own.
        permission_level: options.permission?.(),
        continues_message_id: continuesMessageId,
      });
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        // A run is already active on this conversation — drop the optimistic
        // turn we just queued (it was never accepted) and surface the one
        // that's actually in flight instead of silently discarding this send.
        setMessages(
          reconcile(
            messages.filter((m) => m.id !== userMsg.id && m.id !== assistantId),
          ),
        );
        toast.error("A response is still in progress in this conversation.");
        setSending(false);
        setTitlePending(false);
        if (activeConversationId)
          void resume.reattachToLiveRun(activeConversationId);
        return;
      }
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to reach the assistant.",
      );
      patchById(assistantId, (m) => (m.streaming = false));
      setSending(false);
      setTitlePending(false);
      return;
    }
    activeConversationId = created.conversation_id;
    // Accepted — so the backend has retired the stop marker this turn resumes.
    // Echo that now rather than waiting for the run to finish: the warning is about
    // a turn the operator has visibly just resumed, and leaving it up for the length
    // of the new run reads as the Continue press having done nothing.
    if (continuesMessageId !== undefined)
      patchById(continuesMessageId, (m) => {
        m.blocked = false;
        m.blockedDetail = undefined;
      });
    await drive.driveRun(created.run_id, assistantId, wasNew);
  }

  /** Resume a turn a bound stopped (inactivity/wall-clock timeout or cancel) by
   *  sending a fresh "Continue." turn on the same conversation. Reuses the ordinary
   *  send path, so a small "Continue." bubble appears in the transcript and the
   *  model picks up where the prior turn left off.
   *
   *  ``messageId`` is the stopped turn's branch node id — the backend retires that
   *  turn's stop marker when it accepts the turn, so the warning doesn't linger
   *  under a turn the operator already resumed, and a reload reads the retirement
   *  back from the store rather than resurrecting it. */
  async function continueTurn(messageId?: string): Promise<void> {
    // A blocked turn is settled, so this is a fresh turn — but if a run is already
    // in flight (the operator started a new one), don't inject "Continue." as a
    // steering message; just no-op.
    if (activeConversationId === null || sending()) return;
    await send(CONTINUE_PROMPT, [], messageId);
  }

  /** Cancel the in-flight run for real: tell the backend to stop it (it keeps
   *  running even when the SSE is dropped), then abort the local stream and clear
   *  the streaming state. Safe to call with no active run. */
  async function cancel(): Promise<void> {
    const runId = foldState.activeRunId;
    // Mark the cancel before the abort unwinds the drive, so its `adoptServerMeta`
    // in `finally` keeps the in-flight turn instead of reseating it away.
    cancelled = true;
    if (runId) {
      try {
        await api.post(`/runs/${runId}/cancel`, {});
      } catch (err) {
        // The local abort below still stops the UI; surface but don't block.
        toast.error(
          (err as { detail?: string })?.detail ?? "Unable to cancel the run.",
        );
      }
    }
    foldState.activeRunId = null;
    // `stop`, not `supersede`: the turn really is over, so the drive still has to
    // run its own teardown and reconcile what was persisted.
    drive.stop();
    setMessages(
      produce((m) => {
        // A cancelled turn may currently be `streaming` (normal in-flight) or
        // `detached` (transport gave up, but we still guarded it as in-flight)
        // — either is the one this cancel is aimed at.
        const target = m.find((x) => x.streaming || x.detached);
        if (target) {
          target.streaming = false;
          target.queued = false;
          target.detached = false;
        }
      }),
    );
    setSending(false);
    // A cancel with steering messages still queued: they'll never be injected
    // now, so restore them to the composer. (The drive's own teardown also calls
    // this; it's idempotent, and this covers the detached case it skips.)
    steering.restoreUndelivered();
  }

  // Branching, version-cycling and the rest of what can be done to a recorded turn.
  // They act on the conversation tree rather than on the run in flight, so they take
  // this controller's handles rather than living inside it.
  const branching = createBranchingOps({
    messages,
    setMessages,
    setUsage,
    setSnapshots,
    conversationId: () => activeConversationId,
    sending,
    setSending,
    patchById,
    overrideSelection: () => options.selection?.(),
    driveRun: (runId, assistantId) => drive.driveRun(runId, assistantId),
    reattachToLiveRun: resume.reattachToLiveRun,
    cancel,
    onTurnComplete: () => options.onTurnComplete?.(),
  });

  // Cold-read reattach: a thread loaded mid-stream carries its in-flight run
  // (`options.activeRun`), so resume it — fold the full replay onto a freshly
  // seeded assistant turn and continue live — instead of rendering the thread
  // reply-less. The source is withheld (→ undefined) while history loads, so this
  // never fires on an empty seed; it runs once per run (`reattachedRunId`) and not
  // for a run we're already driving.
  createEffect(() => {
    const ar = options.activeRun?.();
    if (!ar || ar.id === reattachedRunId || ar.id === foldState.activeRunId)
      return;
    reattachedRunId = ar.id;
    void drive.reattachRun(ar.id, { fromSeq: 0 });
  });

  return {
    messages,
    /** The conversation's workspace snapshots (git-style history), newest last. */
    snapshots,
    /** The stream path of this thread's live agent browser, or null when it has none. */
    browserStream,
    /** Drop the live browser — the panel calls this when its socket reports the session
     *  is gone, which is the only signal a reap between turns can produce. */
    clearBrowserStream: () => setBrowserStream(null),
    toggleSnapshotKeeper: branching.toggleSnapshotKeeper,
    sending,
    errored,
    /** True while the live run's transport is detached (reconnect budget
     *  exhausted) — the run may still be alive server-side, awaiting a
     *  manual/automatic re-attach rather than being over. */
    detached: drive.detached,
    /** True while a sensitive tool call has parked this run awaiting the
     *  operator's decision — the main room mirrors it to the global
     *  `awaitingApproval` echo (nav rail warn tone, favicon attention tint). */
    awaitingApproval: approvals.awaitingApproval,
    titlePending,
    reattaching: drive.reattaching,
    usage,
    stats,
    plan,
    /** The run currently streaming into this store, or null. */
    activeRunId: () => foldState.activeRunId,
    /** Highest event seq folded so far — the resume point for a reattach. */
    lastSeq: () => foldState.maxFoldedSeq,
    send,
    /** Resume a turn a bound stopped by sending a fresh "Continue." turn. */
    continueTurn,
    cancel,
    /** Withdraw a queued (not-yet-injected) steering message from the live run. */
    withdrawQueued: (id: string) => steering.withdrawQueued(id),
    /** Rewrite a queued (not-yet-injected) steering message in place. */
    editQueued: (id: string, text: string) => steering.editQueued(id, text),
    /** Text of queued messages the run never consumed (restored on terminal) —
     *  the screen prefills the composer with it, then clears it. */
    undeliveredDraft: steering.undeliveredDraft,
    clearUndeliveredDraft: steering.clearUndeliveredDraft,
    reattachRun: drive.reattachRun,
    resolveApproval: approvals.resolveApproval,
    resolveHostCommands: approvals.resolveHostCommands,
    regenerate: branching.regenerate,
    edit: branching.edit,
    switchVersion: branching.switchVersion,
    rewind: branching.rewind,
    compactNow: branching.compactNow,
    removeMessage: branching.removeMessage,
    toggleMessagePin: branching.toggleMessagePin,
  };
}
