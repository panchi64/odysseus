/**
 * The streaming controller — one thread's live state, and the run driving it.
 *
 * Everything here is about a *run*: opening its SSE reader, keeping the optimistic
 * transcript in step with what the backend actually accepted, surviving a dropped
 * transport, and reconciling with the persisted tree when it ends. What each event *means*
 * is `fold.ts`'s job, and what the operator can do to an already-recorded turn is
 * `branching.ts`'s; keeping those out leaves this file with one question — is a turn in
 * flight, and where is it up to.
 *
 * **The optimistic store is authoritative for the thread it is on.** A turn's messages are
 * persisted only when it finishes, so a refetch mid-stream reads an empty conversation. The
 * reseed effect therefore refuses to clobber a live thread, and `adoptServerMeta` takes
 * only ids and version metadata from the backend rather than reseating wholesale — except
 * where the histories genuinely disagree in length, which means a turn produced nothing to
 * persist.
 *
 * **Detached is not ended.** When the transport exhausts its reconnect budget the run may
 * still be alive server-side. That state keeps `activeRunId` and `sending` reporting it as
 * in flight, so the composer stays guarded and the visibility/online listeners still have
 * something to reattach to; only a cancel, a supersede, or a successful reattach settles it.
 *
 * **A generation counter guards every teardown.** A reattach or a thread switch supersedes
 * the drive in flight; that drive's `finally` must not clear state the new one now owns.
 */

import { createEffect, createMemo, createSignal, onCleanup } from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import { api, isApiError } from "~/lib/api";
import { effectiveSelection, type ModelSelection } from "~/lib/stores/models";
import {
  StreamDetachedError,
  streamRun,
  type PlanItem,
  type RunEvent,
} from "~/lib/stream";
import type { SessionMode } from "~/lib/modes";
import { toast } from "~/ui";
import { CONTINUE_PROMPT } from "../data/constants";
import {
  bumpGrantsRevision,
  fetchBrowserSession,
  fetchPlan,
} from "../data/conversations";
import { toActiveRun } from "../data/mappers";
import type { ChatCreatedDTO, ConversationDetailDTO } from "../data/wire";
import type {
  ActiveRun,
  ApprovalDecision,
  ChatMessage,
  ContextUsage,
  ConversationStats,
  HostCommandBlock,
  PermissionLevel,
  ViewSnapshotRef,
} from "../model";
import {
  createBranchingOps,
  reseatFromDetail,
  type TranscriptStore,
} from "./branching";
import { createFolder, type FoldState } from "./fold";
import { nextId } from "./patch";

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
  // starts (in `driveRun`). The main room mirrors it to the global `runErrored` echo
  // so the favicon can flag a failed run — compare panes keep it local.
  const [errored, setErrored] = createSignal(false);
  // True when the live run's SSE transport exhausted its reconnect budget —
  // the run may still be alive server-side, but this client lost its
  // connection to it. Cleared when the next run/reattach starts (`driveRun`).
  // Mirrors `errored`'s pattern, but distinct: a detached turn isn't "over",
  // so the composer and the resume()/reattach paths must keep treating it as
  // in-flight rather than settled.
  const [detached, setDetached] = createSignal(false);
  // True while the room has a live, undecided approval — folded by `approval.required`
  // (both the generic approval card and the host-command terminal's pending phase) and
  // gated on `sending()` so it clears the moment the run stops being in flight, whether
  // by resolution (the approval/host-command block is filtered/re-phased out of
  // `messages` on submit — see `resolveApproval`/`resolveHostCommands`), a cancel, or the
  // run ending. A derived memo rather than its own set/clear pair: the blocks are already
  // the single source of truth for "is something still pending", so this only reads them.
  const awaitingApproval = createMemo(
    () =>
      sending() &&
      messages.some((m) =>
        m.blocks?.some(
          (b) =>
            (b.kind === "approval" && !b.approval.stale) ||
            (b.kind === "host_command" && b.command.phase === "pending"),
        ),
      ),
  );
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
  // True while a reattach (replay from a known run) is folding in — drives the
  // "RESYNCING…" affordance, distinct from a fresh turn's `sending`.
  const [reattaching, setReattaching] = createSignal(false);
  // Text of steering messages that were still queued when their run reached
  // terminal (cancel/error/timeout) — never delivered to the model. The screen
  // hands it back to the composer as a prefill so the operator's words aren't
  // lost; cleared once consumed.
  const [undeliveredDraft, setUndeliveredDraft] = createSignal<string | null>(
    null,
  );
  let controller: AbortController | null = null;
  // The run-scoped bookkeeping the fold advances and this controller resets: the
  // high-water seq, the bubble events land on, the plan's revision counter, and the
  // run currently streaming. One object, shared by reference with the folder.
  const foldState: FoldState = {
    maxFoldedSeq: 0,
    foldTarget: null,
    planRevision: 0,
    activeRunId: null,
  };
  // The last run a cold-read reattach was kicked off for, so the load effect fires
  // at most once per run even if the session resource re-emits the same value.
  let reattachedRunId: string | null = null;
  // Bumped whenever a drive is superseded (reattach aborts the prior reader, or a
  // thread switch tears it down). A driveRun whose generation is stale skips its
  // teardown so an aborted stalled reader can't clear the state — or refetch the
  // wrong thread — out from under the drive that replaced it.
  let driveGen = 0;
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

  function patchById(id: string, fn: (m: ChatMessage) => void): void {
    const i = messages.findIndex((m) => m.id === id);
    if (i < 0) return;
    setMessages(produce((m) => fn(m[i])));
  }

  const foldEvent = createFolder({
    state: foldState,
    messages,
    setMessages,
    setSnapshots,
    setBrowserStream,
    setPlan,
    setUsage,
    setStats,
    setErrored,
  });

  // Re-seed when the conversation changes. Guard: don't wipe a live thread while
  // its server history is still loading (the just-created thread re-loads with
  // identical content, so skipping avoids an empty flash).
  const INIT = Symbol("init");
  let lastKey: string | null | typeof INIT = INIT;
  let lastSource: ChatMessage[] | undefined | typeof INIT = INIT;
  createEffect(() => {
    const k = key();
    const source = initial();
    if (k === lastKey && source === lastSource) return;
    // Record the transition before any early return below, or the bookkeeping
    // goes stale: skipping these on the authoritative-store guard left `lastKey`
    // pinned at its pre-adoption value, so a later transition back to that value
    // (e.g. compare's teardown reverting the key to null) read as "no change"
    // and the transcript never cleared.
    lastKey = k;
    lastSource = source;
    // The live store is authoritative for the thread we're already on: never let
    // a (re)fetch of its server history clobber it. This keeps a freshly-created
    // thread's streamed messages — including live-only fields the history
    // projection doesn't carry (preview, artifacts, runId) — when it adopts its
    // backend id, and avoids an empty flash while that history loads.
    if (k === activeConversationId && messages.length > 0) return;
    controller?.abort();
    controller = null;
    driveGen++; // supersede any in-flight drive so its finally skips teardown
    setSending(false);
    setReattaching(false);
    setDetached(false);
    // A new thread starts a fresh event sequence; drop the prior run's fold/resume
    // bookkeeping so its seqs don't suppress the next run's events.
    foldState.maxFoldedSeq = 0;
    foldState.activeRunId = null;
    foldState.foldTarget = null;
    // Forget which run we've already reattached-to: leaving this thread (still
    // detached/mid-stream) and returning later must let the cold-reattach effect
    // fire again for the same run id, rather than permanently ignoring a run it
    // saw once, in some earlier visit, before this stream instance existed.
    reattachedRunId = null;
    activeConversationId = k;
    // A null key is a new, unsaved conversation: it has no persisted history, so
    // the only `source` here is the seam resource's *retained* value from the
    // thread we just left (Solid keeps a resource's last value once its id goes
    // null). Seeding from it would keep a just-deleted thread's messages on
    // screen, so a null key always starts empty.
    const seed = k === null ? [] : source ? source.slice() : [];
    setMessages(reconcile(seed));
    // Seed the meter from the loaded thread's reconstructed state (null for a new
    // conversation, or one whose usage/window couldn't be determined).
    setUsage(k === null ? null : (options.initialContext?.() ?? null));
    // Seeded from the loaded thread, not cleared: the backend rebuilds the readout
    // from the stored messages, so an existing conversation reports what it has spent
    // before its next turn runs rather than starting the line blank.
    setStats(k === null ? null : (options.initialStats?.() ?? null));
    // Seed the git-style snapshot history from the loaded thread (empty for a new
    // conversation); the live `view.snapshot` event appends to it from here.
    setSnapshots(k === null ? [] : (options.initialSnapshots?.() ?? []));
    // A live browser belongs to the thread, not to the client — so a switch clears the
    // previous thread's and asks the backend whether *this* one has one.
    setBrowserStream(null);
    // The plan is owned by the backend and survives reloads, so a thread switch clears
    // the old one and refetches rather than carrying the previous thread's list over.
    setPlan([]);
    if (k !== null) {
      const requested = k;
      // Snapshot the live-update counter: opening a thread whose run is mid-turn races
      // the backfill against `plan.updated`, and the fetch answers with pre-mutation
      // state. Without this the slower fetch wins and the panel goes stale until the
      // next mutation — which may never come.
      const seenAtRequest = foldState.planRevision;
      void fetchPlan(requested)
        .then((items) => {
          // Drop it if the operator has since left the thread, or the stream already
          // said something newer.
          if (key() === requested && foldState.planRevision === seenAtRequest)
            setPlan(items);
        })
        .catch(() => {
          // The panel is an aid, not the transcript — a failed backfill leaves it
          // empty and the next `plan.updated` fills it in.
        });
      void fetchBrowserSession(requested)
        .then((path) => {
          // Only if the operator is still on this thread, and the stream hasn't already
          // announced a session (which would be newer than this answer).
          if (key() === requested && browserStream() === null)
            setBrowserStream(path);
        })
        .catch(() => {
          // Browser control may not be wired at all; no panel is the right answer.
        });
    }
  });

  /** Drop any still-pending steering bubbles and hand their text back to the
   *  composer (`undeliveredDraft`). Idempotent — a no-op when nothing is
   *  pending — so the drive teardown and `cancel` can both call it safely. */
  function restoreUndelivered(): void {
    const leftovers = messages.filter((m) => m.queuedPending);
    if (leftovers.length === 0) return;
    setMessages(reconcile(messages.filter((m) => !m.queuedPending)));
    const text = leftovers.map((m) => m.content).join("\n");
    setUndeliveredDraft((prev) => (prev ? `${prev}\n${text}` : text));
    toast.warn(
      "Your queued message wasn't delivered — it's back in the input.",
    );
  }

  /** Drive a started run to completion: open the SSE, fold every event onto the
   *  given assistant message, and on end clear streaming/sending, fire the
   *  lifecycle callbacks, and refresh the session list. Shared by `send` and the
   *  branching ops (regenerate/edit) so the run tail lives in one place.
   *  `wasNew` reports a freshly-created conversation so its id can be adopted. */
  async function driveRun(
    runId: string,
    assistantId: string,
    wasNew = false,
    fromSeq?: number,
    onConnected?: () => void,
  ): Promise<void> {
    const myGen = ++driveGen;
    cancelled = false; // a fresh run clears any prior cancel signal
    foldState.activeRunId = runId;
    setErrored(false); // a fresh run supersedes any prior failure
    setDetached(false); // a fresh run/reattach supersedes any prior detach
    // Re-anchor the fold high-water mark to this run's sequence. Each run owns a
    // fresh event stream whose seq restarts at 1, so a new turn (fromSeq omitted →
    // 0) must drop the *previous* run's mark — otherwise its early events (seq ≤
    // that stale mark) are suppressed in `foldEvent` and the answer streams in
    // blank until the counter catches up (or never, if this turn is shorter). A
    // reattach passes `fromSeq` = the last seq it folded, replaying only the gap.
    foldState.maxFoldedSeq = fromSeq ?? 0;
    // Events start folding onto the placeholder; a `message.injected` boundary
    // retargets this as the run's segments split.
    foldState.foldTarget = assistantId;
    patchById(assistantId, (m) => {
      m.runId = runId;
      m.detached = false; // a fresh drive/reattach supersedes any prior detach
    });
    let connected = false;
    let detachedNow = false;
    try {
      controller = new AbortController();
      await streamRun(runId, {
        signal: controller.signal,
        fromSeq,
        onEvent: (ev: RunEvent) => {
          // First event = the transport is live again; let a reattach drop its
          // "RESYNCING…" badge here, so it shows only across the reconnect latency.
          // It's also the queued→streaming transition: the backend only starts
          // emitting once the run actually clears the concurrency semaphore, so
          // the first frame (of any kind) is what tells us it's no longer queued.
          if (!connected) {
            connected = true;
            patchById(assistantId, (m) => (m.queued = false));
            onConnected?.();
          }
          foldEvent(assistantId, ev);
        },
      });
    } catch (err) {
      if (myGen !== driveGen) {
        // superseded — nothing to surface
      } else if (err instanceof StreamDetachedError) {
        // The transport gave up reconnecting, but the run may still be alive
        // server-side: don't treat the turn as ended. Leave it in a distinct
        // "detached" state (not streaming, not settled) with a re-attach
        // affordance, and keep `activeRunId`/`sending` as-is so the composer
        // stays guarded and the visibility/online resume listeners still see
        // an in-flight run to reattach to.
        detachedNow = true;
        setDetached(true);
        patchById(foldState.foldTarget ?? assistantId, (m) => {
          m.streaming = false;
          m.queued = false;
          m.detached = true;
        });
        toast.error(
          "Connection lost. The response may still be running — reconnect to continue.",
        );
      } else {
        toast.error(
          (err as { detail?: string })?.detail ??
            "Unable to reach the assistant.",
        );
      }
    } finally {
      // Skip teardown when superseded by a reattach/thread-switch (that drive
      // owns the state now, and clearing it here would race it) or when this
      // drive ended detached — the run isn't actually over, so `activeRunId`/
      // `sending` must keep reporting it as in-flight until it's re-attached,
      // cancelled, or superseded.
      if (myGen === driveGen && !detachedNow) {
        foldState.activeRunId = null;
        patchById(foldState.foldTarget ?? assistantId, (m) => {
          m.streaming = false;
          m.detached = false; // the turn is genuinely over — clear any stale banner
          m.queued = false; // defensive: covers a resolve with no frames ever folded
        });
        // Steering messages the run never consumed (it was cancelled/errored/
        // timed out before their boundary): hand the text back to the composer
        // rather than silently dropping the operator's words.
        restoreUndelivered();
        setSending(false);
        setTitlePending(false); // turn ended — clear even if no title landed
        if (wasNew && activeConversationId) {
          options.onConversationStarted?.(activeConversationId);
        }
        options.onTurnComplete?.();
        // Adopt the backend's authoritative ids + version metadata for the turn
        // just recorded — without this the live message keeps its client id and a
        // stale version count, so the ‹k/n› cycler never appears and a later
        // regenerate/edit/delete/pin would address an id the backend doesn't know.
        await adoptServerMeta();
      }
    }
  }

  /** Reattach to a run that's already streaming (or just finished) and fold what
   *  we missed, then continue live. Two callers:
   *  - resume after a stalled/dropped transport (a backgrounded tab): the
   *    assistant message still exists, so replay from `fromSeq` = the last seq we
   *    folded — only the tail re-applies (the seq guard drops the overlap).
   *  - a cold read mid-stream (page reload): no assistant turn exists yet, so seed
   *    an empty one bound to the run and replay the whole buffer (`fromSeq` 0).
   *  Reuses `driveRun`, so the shared finally clears streaming/sending and
   *  reconciles the persisted turn once the run ends. */
  async function reattachRun(
    runId: string,
    opts: { fromSeq: number },
  ): Promise<void> {
    // Abort a stalled/old reader first so it can't keep folding beside the new one
    // (its drive is superseded by the generation bump inside the next driveRun).
    controller?.abort();
    controller = null;
    // The *last* matching turn: a steered run splits into several assistant
    // segments sharing one runId, and only the newest is the live one.
    let assistantId = messages.findLast(
      (m) => m.runId === runId && m.role === "assistant",
    )?.id;
    const seeded = assistantId === undefined;
    if (assistantId === undefined) {
      assistantId = nextId("a");
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        blocks: [],
        streaming: true,
        runId,
        createdAt: new Date().toISOString(),
      };
      setMessages(produce((m) => m.push(assistantMsg)));
    } else {
      patchById(assistantId, (m) => {
        m.streaming = true;
        m.detached = false; // re-attaching supersedes the "connection lost" banner
      });
    }
    // `driveRun` re-anchors `maxFoldedSeq` to the `fromSeq` passed below, so the
    // resume replays only the gap after the last folded event.
    setSending(true);
    setReattaching(true);
    try {
      // Clears RESYNCING on the first folded event; the finally is the safety net
      // for a reattach that never connects (e.g. an immediate 404).
      await driveRun(runId, assistantId, false, opts.fromSeq, () =>
        setReattaching(false),
      );
    } finally {
      setReattaching(false);
    }
    // A freshly-seeded turn that folded nothing means the run was gone (evicted, or
    // lost to a server restart): fall back to the persisted thread so a finished
    // answer still shows rather than a blank assistant turn. Skip this when the
    // attempt itself ended detached (reconnect budget exhausted, not a 404/empty
    // buffer) — the run may still be alive, so reseating from the (possibly
    // reply-less) persisted detail here would discard the re-attach affordance
    // for no reason; leave the seed detached and let the operator/resume retry.
    if (
      !detached() &&
      seeded &&
      foldState.maxFoldedSeq === opts.fromSeq &&
      activeConversationId !== null
    ) {
      try {
        reseat(
          await api.get<ConversationDetailDTO>(
            `/conversations/${activeConversationId}`,
          ),
        );
      } catch {
        // Leave the seed; the next navigation/refresh reconciles it.
      }
    }
  }

  /** Reconcile the live store with the backend's projected active path after a
   *  turn: adopt each turn's real node id + version index/count + pin by position
   *  (the store mirrors the same active path), leaving live-only fields the cold
   *  projection doesn't carry — `preview`, `runId` — untouched. A length mismatch
   *  (e.g. a turn that produced no persisted answer) falls back to a full reseat.
   *  Best-effort: a failed read leaves the optimistic store in place. */
  async function adoptServerMeta(): Promise<void> {
    if (activeConversationId === null) return;
    const convAtStart = activeConversationId;
    const lenAtStart = messages.length;
    let detail: ConversationDetailDTO;
    try {
      detail = await api.get<ConversationDetailDTO>(
        `/conversations/${convAtStart}`,
      );
    } catch {
      return;
    }
    // Bail if the store moved under us while the read was in flight: the operator
    // started another turn (length changed — the composer re-enabled the instant
    // streaming stopped) or switched threads. Reconciling now would reseat over the
    // new turn's optimistic messages and freeze its stream; that turn reconciles
    // itself when it completes.
    if (activeConversationId !== convAtStart || messages.length !== lenAtStart)
      return;
    const server = detail.messages;
    if (server.length !== messages.length) {
      // A shorter backend history normally means a turn produced no persisted
      // answer, so reseat to drop the optimistic turn. But a *cancelled* turn also
      // persists nothing — there reseating would discard the in-flight turn the
      // operator chose to keep (and blank a brand-new chat), so leave the store as
      // is; the next completed turn reconciles it.
      if (!cancelled) reseat(detail);
      return;
    }
    setMessages(
      produce((list) => {
        for (let i = 0; i < list.length; i++) {
          list[i].id = server[i].id;
          list[i].versionIndex = server[i].version_index;
          list[i].versionCount = server[i].version_count;
          list[i].pinned = server[i].pinned;
          // The store owns the stop marker (a continue retires it), so take its
          // word here too — otherwise a turn cleared server-side stays warned
          // locally until a full reseat.
          list[i].blocked = server[i].blocked_reason != null;
          list[i].blockedDetail = server[i].blocked_reason ?? undefined;
        }
      }),
    );
  }

  /** After a 409 (the backend already has a run active on this conversation —
   *  a parallel submit, a stale UI, or a second tab/device) look up the
   *  conversation's current active run and reattach to it, so the turn that's
   *  actually in flight becomes visible instead of silently going nowhere.
   *  Best-effort: a failed lookup just leaves the composer free to retry. */
  async function reattachToLiveRun(conversationId: string): Promise<void> {
    try {
      const detail = await api.get<ConversationDetailDTO>(
        `/conversations/${conversationId}`,
      );
      // Bail if the operator navigated to a different thread while the read was
      // in flight — reattachRun's abort+seed-push would otherwise contaminate
      // whatever conversation is live now with this one's run.
      if (activeConversationId !== conversationId) return;
      const ar = toActiveRun(detail.active_run);
      if (ar) await reattachRun(ar.id, { fromSeq: 0 });
    } catch {
      // Best effort — the operator can retry manually.
    }
  }

  /** After a submitted approval/host-command decision 409s (the run had already
   *  resumed elsewhere — a second tab, a retried request — by the time this one
   *  landed), the pending card's decision is moot. Refetch so the transcript
   *  reconciles with whatever the winning decision actually did, re-attaching to
   *  the run if it's still in flight. Unlike `reattachToLiveRun`, this always
   *  reseats — the winning decision may have already finished the run entirely,
   *  not just still be running. Best-effort: a failed refetch leaves the caller's
   *  stale marker as the only signal, but never re-throws into an unhandled turn. */
  async function reconcileStaleDecision(): Promise<void> {
    if (activeConversationId === null) return;
    const convAtStart = activeConversationId;
    try {
      const detail = await api.get<ConversationDetailDTO>(
        `/conversations/${convAtStart}`,
      );
      // Bail if the operator switched threads while the read was in flight — a
      // different thread is live now, so this stale decision's conversation
      // must not overwrite its store.
      if (activeConversationId !== convAtStart) return;
      reseat(detail);
      const ar = toActiveRun(detail.active_run);
      if (ar) await reattachRun(ar.id, { fromSeq: 0 });
    } catch {
      // Best effort — the stale marker set by the caller still holds.
    }
  }

  /** Send while a run is live: the backend queues the message into that run
   *  (injected at its next boundary) — or, if the run ended in the meantime,
   *  starts a fresh turn; the response tells us which, so this client never
   *  picks. The optimistic bubble renders QUEUED until `message.injected`
   *  promotes it (or a withdraw/terminal removes it). */
  async function sendWhileStreaming(text: string): Promise<void> {
    if (activeConversationId === null) {
      // The first turn's POST hasn't resolved yet, so there's no conversation to
      // queue against. The composer already cleared itself — hand the text back
      // rather than dropping it.
      setUndeliveredDraft((prev) => (prev ? `${prev}\n${text}` : text));
      return;
    }
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: text.trim(),
      createdAt: new Date().toISOString(),
      queuedPending: true,
    };
    setMessages(produce((m) => m.push(userMsg)));
    let created: ChatCreatedDTO;
    try {
      created = await api.post<ChatCreatedDTO>("/chat", {
        prompt: text.trim(),
        conversation_id: activeConversationId,
      });
    } catch (err) {
      // Not accepted (a regenerate/edit holds the claim, or transport failed):
      // roll the bubble back so the transcript only shows what the backend has.
      setMessages(reconcile(messages.filter((m) => m.id !== userMsg.id)));
      toast.error(
        isApiError(err) && err.status === 409
          ? "Can't queue this message right now — try again in a moment."
          : ((err as { detail?: string })?.detail ??
              "Unable to reach the assistant."),
      );
      return;
    }
    if (created.queued_message_id) {
      // Queued into the live run. The `message.queued` fold may have already
      // tagged the bubble via the open stream; this is the fallback tag.
      patchById(userMsg.id, (m) => {
        if (!m.queuedMessageId) m.queuedMessageId = created.queued_message_id!;
      });
      return;
    }
    // The run went terminal just before the POST landed: the backend started a
    // fresh run for this message instead. Promote the bubble to a normal turn
    // and drive the new run like any other send.
    patchById(userMsg.id, (m) => (m.queuedPending = false));
    const assistantId = nextId("a");
    setMessages(
      produce((m) =>
        m.push({
          id: assistantId,
          role: "assistant",
          model: (options.selection?.() ?? effectiveSelection())?.model,
          content: "",
          blocks: [],
          streaming: true,
          queued: true,
          createdAt: new Date().toISOString(),
        }),
      ),
    );
    setSending(true);
    activeConversationId = created.conversation_id;
    await driveRun(created.run_id, assistantId, false);
  }

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
      await sendWhileStreaming(text);
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
        if (activeConversationId) void reattachToLiveRun(activeConversationId);
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
    await driveRun(created.run_id, assistantId, wasNew);
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
    controller?.abort();
    controller = null;
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
    setDetached(false);
    // A cancel with steering messages still queued: they'll never be injected
    // now, so restore them to the composer. (The drive's own teardown also calls
    // this; it's idempotent, and this covers the detached case it skips.)
    restoreUndelivered();
  }

  /** Withdraw a steering message that's still queued on the live run. No
   *  optimistic removal: a 404 means the run consumed it in the meantime — the
   *  message is part of the turn and its bubble must stay. On success the
   *  bubble drops here and the `message.withdrawn` fold is a no-op. */
  async function withdrawQueued(queuedMessageId: string): Promise<void> {
    const runId = foldState.activeRunId;
    if (!runId) return;
    try {
      await api.del(`/runs/${runId}/messages/${queuedMessageId}`);
      setMessages(
        reconcile(
          messages.filter(
            (m) => !(m.queuedMessageId === queuedMessageId && m.queuedPending),
          ),
        ),
      );
    } catch (err) {
      if (isApiError(err) && err.status === 404) {
        toast.warn(
          "Too late to withdraw — the message already reached the model.",
        );
      } else {
        toast.error(
          (err as { detail?: string })?.detail ??
            "Unable to withdraw the message.",
        );
      }
    }
  }

  /** Rewrite a steering message that's still queued on the live run (it keeps
   *  its id and place in the queue). No optimistic update: the bubble changes
   *  only once the backend accepts, and a 404 means the run consumed the
   *  message in the meantime — the original text is what the model saw, so the
   *  bubble must keep it. */
  async function editQueued(
    queuedMessageId: string,
    text: string,
  ): Promise<void> {
    const runId = foldState.activeRunId;
    if (!runId) return;
    try {
      await api.patch(`/runs/${runId}/messages/${queuedMessageId}`, { text });
      setMessages(
        produce((list) => {
          const bubble = list.find(
            (m) => m.queuedMessageId === queuedMessageId && m.queuedPending,
          );
          if (bubble) bubble.content = text;
        }),
      );
    } catch (err) {
      if (isApiError(err) && err.status === 404) {
        toast.warn("Too late to edit — the message already reached the model.");
      } else {
        toast.error(
          (err as { detail?: string })?.detail ?? "Unable to edit the message.",
        );
      }
    }
  }

  /** POST a batch of approval decisions for a message's run, then apply an
   *  optimistic patch. The open run stream resumes with the results — the parked
   *  run requires a decision covering *every* pending call, which is why each
   *  surface batches its decisions into one POST. */
  async function submitDecisions(
    messageId: string,
    decisions: ApprovalDecision[],
    optimistic: (m: ChatMessage) => void,
  ): Promise<void> {
    const msg = messages.find((m) => m.id === messageId);
    if (!msg?.runId) return;
    try {
      await api.post(`/runs/${msg.runId}/approve`, { decisions });
      patchById(messageId, optimistic);
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
        patchById(messageId, (m) => {
          for (const b of m.blocks ?? []) {
            if (b.kind === "approval") b.approval.stale = true;
            else if (b.kind === "host_command" && b.command.phase === "pending")
              b.command.phase = "stale";
          }
        });
        toast.error("This decision was already made elsewhere.");
        void reconcileStaleDecision();
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

  /** Decide a message's pending approvals; the cards clear once submitted. */
  const resolveApproval = (messageId: string, decisions: ApprovalDecision[]) =>
    submitDecisions(messageId, decisions, (m) => {
      if (m.blocks) m.blocks = m.blocks.filter((b) => b.kind !== "approval");
    });

  /** Decide a message's host-command approvals. Approved commands begin running
   *  and denied ones close out optimistically; the stream confirms the outcome. */
  const resolveHostCommands = (
    messageId: string,
    decisions: ApprovalDecision[],
  ) =>
    submitDecisions(messageId, decisions, (m) => {
      for (const d of decisions) {
        const b = m.blocks?.find(
          (x): x is HostCommandBlock =>
            x.kind === "host_command" &&
            x.command.toolCallId === d.tool_call_id,
        );
        if (b) b.command.phase = d.approved ? "running" : "denied";
      }
    });

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
    driveRun: (runId, assistantId) => driveRun(runId, assistantId),
    reattachToLiveRun,
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
    void reattachRun(ar.id, { fromSeq: 0 });
  });

  onCleanup(() => controller?.abort());

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
    detached,
    /** True while a sensitive tool call has parked this run awaiting the
     *  operator's decision — the main room mirrors it to the global
     *  `awaitingApproval` echo (nav rail warn tone, favicon attention tint). */
    awaitingApproval,
    titlePending,
    reattaching,
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
    withdrawQueued,
    /** Rewrite a queued (not-yet-injected) steering message in place. */
    editQueued,
    /** Text of queued messages the run never consumed (restored on terminal) —
     *  the screen prefills the composer with it, then clears it. */
    undeliveredDraft,
    clearUndeliveredDraft: () => setUndeliveredDraft(null),
    reattachRun,
    resolveApproval,
    resolveHostCommands,
    regenerate: branching.regenerate,
    edit: branching.edit,
    switchVersion: branching.switchVersion,
    rewind: branching.rewind,
    compactNow: branching.compactNow,
    removeMessage: branching.removeMessage,
    toggleMessagePin: branching.toggleMessagePin,
  };
}
