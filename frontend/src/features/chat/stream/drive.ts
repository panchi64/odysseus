/**
 * Driving one run's SSE to its end — and picking one back up that got away.
 *
 * Everything a turn needs *after* the backend has accepted it: open the reader, fold what
 * arrives onto the right bubble, and tear the whole thing down exactly once when it ends.
 * What a frame means is `fold.ts`'s, what to send is the controller's; this file only ever
 * answers "is a turn in flight, and where is it up to".
 *
 * **Detached is not ended.** When the transport exhausts its reconnect budget the run may
 * still be alive server-side, so the drive leaves the turn in a third state — not
 * streaming, not settled — and *skips its teardown*. `sending` and the active run id keep
 * reporting it as in flight, which is what leaves the composer guarded and gives the
 * visibility/online listeners something to reattach to. Only a cancel, a supersede, or a
 * successful reattach settles it.
 *
 * **A generation counter guards every teardown.** A reattach or a thread switch supersedes
 * the drive in flight; that drive's `finally` must not clear state the new one now owns.
 * This is the difference between the two ways to stop: `supersede` orphans the running
 * drive (a new owner is taking over), while `stop` aborts the reader but lets that drive
 * finish tearing its own turn down — which is what a cancel wants, since the turn really
 * is over and still needs reconciling.
 *
 * **Each run restarts the sequence at 1.** So the fold's high-water mark is re-anchored
 * per drive: a fresh turn to 0, and a reattach to the last seq it folded, which replays
 * only the gap. Carrying the previous run's mark over suppresses the new turn's opening
 * events and the answer streams in blank.
 */

import { createSignal, onCleanup, type Accessor } from "solid-js";
import { produce, type SetStoreFunction } from "solid-js/store";
import { StreamDetachedError, streamRun, type RunEvent } from "~/lib/stream";
import { toast } from "~/ui";
import type { ChatMessage } from "../model";
import type { FoldState } from "./fold";
import { nextId, type PatchById } from "./patch";

/** What the drive is allowed to touch. Passed in rather than closed over, so the run
 *  lifecycle can be reasoned about without the store, the seam and the composer's
 *  state all being in scope at once. */
export interface RunDriveDeps {
  messages: ChatMessage[];
  setMessages: SetStoreFunction<ChatMessage[]>;
  patchById: PatchById;
  /** The run-scoped bookkeeping, shared by reference with the folder. */
  state: FoldState;
  foldEvent: (assistantId: string, ev: RunEvent) => void;
  setSending: (value: boolean) => void;
  setErrored: (value: boolean) => void;
  setTitlePending: (value: boolean) => void;
  /** Clear the operator's cancel flag — a fresh run supersedes any prior cancel. */
  clearCancelled: () => void;
  /** Hand back steering messages the run never consumed. */
  restoreUndelivered: () => void;
  /** The thread the stream is bound to, read once a turn has settled. */
  conversationId: () => string | null;
  /** Adopt the backend's ids for the turn just recorded. Late-bound: the reconcilers
   *  need `reattachRun`, so they are built after this and reached through a thunk. */
  adoptServerMeta: () => Promise<void>;
  /** Fall back to the persisted thread when a reattach folds nothing. Late-bound for
   *  the same reason. */
  recoverLostRun: () => Promise<void>;
  onConversationStarted?: (id: string) => void;
  onTurnComplete?: () => void;
}

export interface RunDrive {
  /** True while the live run's transport is detached (reconnect budget exhausted) —
   *  the run may still be alive server-side, awaiting a re-attach rather than over. */
  detached: Accessor<boolean>;
  /** True while a reattach (replay from a known run) is folding in — drives the
   *  "RESYNCING…" affordance, distinct from a fresh turn's `sending`. */
  reattaching: Accessor<boolean>;
  driveRun: (
    runId: string,
    assistantId: string,
    wasNew?: boolean,
    fromSeq?: number,
    onConnected?: () => void,
  ) => Promise<void>;
  reattachRun: (runId: string, opts: { fromSeq: number }) => Promise<void>;
  /** Take ownership away from whatever drive is running: abort its reader and
   *  orphan its teardown, because the caller is about to own this state. */
  supersede: () => void;
  /** Stop reading, but leave the running drive's teardown to it — the turn is over
   *  and still has to be settled and reconciled. */
  stop: () => void;
}

export function createRunDrive(deps: RunDriveDeps): RunDrive {
  const [detached, setDetached] = createSignal(false);
  const [reattaching, setReattaching] = createSignal(false);
  let controller: AbortController | null = null;
  // Bumped whenever a drive is superseded (a reattach aborts the prior reader, or a
  // thread switch tears it down). A driveRun whose generation is stale skips its
  // teardown so an aborted stalled reader can't clear the state — or refetch the
  // wrong thread — out from under the drive that replaced it.
  let driveGen = 0;

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
    deps.clearCancelled(); // a fresh run clears any prior cancel signal
    deps.state.activeRunId = runId;
    deps.setErrored(false); // a fresh run supersedes any prior failure
    setDetached(false); // a fresh run/reattach supersedes any prior detach
    // Re-anchor the fold high-water mark to this run's sequence (see the header).
    deps.state.maxFoldedSeq = fromSeq ?? 0;
    // Events start folding onto the placeholder; a `message.injected` boundary
    // retargets this as the run's segments split.
    deps.state.foldTarget = assistantId;
    deps.patchById(assistantId, (m) => {
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
            deps.patchById(assistantId, (m) => (m.queued = false));
            onConnected?.();
          }
          deps.foldEvent(assistantId, ev);
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
        deps.patchById(deps.state.foldTarget ?? assistantId, (m) => {
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
        deps.state.activeRunId = null;
        deps.patchById(deps.state.foldTarget ?? assistantId, (m) => {
          m.streaming = false;
          m.detached = false; // the turn is genuinely over — clear any stale banner
          m.queued = false; // defensive: covers a resolve with no frames ever folded
        });
        // Steering messages the run never consumed (it was cancelled/errored/
        // timed out before their boundary): hand the text back to the composer
        // rather than silently dropping the operator's words.
        deps.restoreUndelivered();
        deps.setSending(false);
        deps.setTitlePending(false); // turn ended — clear even if no title landed
        const conversationId = deps.conversationId();
        if (wasNew && conversationId) {
          deps.onConversationStarted?.(conversationId);
        }
        deps.onTurnComplete?.();
        // Adopt the backend's authoritative ids + version metadata for the turn
        // just recorded — without this the live message keeps its client id and a
        // stale version count, so the ‹k/n› cycler never appears and a later
        // regenerate/edit/delete/pin would address an id the backend doesn't know.
        await deps.adoptServerMeta();
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
    let assistantId = deps.messages.findLast(
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
      deps.setMessages(produce((m) => m.push(assistantMsg)));
    } else {
      deps.patchById(assistantId, (m) => {
        m.streaming = true;
        m.detached = false; // re-attaching supersedes the "connection lost" banner
      });
    }
    // `driveRun` re-anchors `maxFoldedSeq` to the `fromSeq` passed below, so the
    // resume replays only the gap after the last folded event.
    deps.setSending(true);
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
    // Skip the recovery when the attempt itself ended detached (reconnect budget
    // exhausted, not a 404/empty buffer) — the run may still be alive, so reseating
    // from the (possibly reply-less) persisted detail here would discard the
    // re-attach affordance for no reason; leave the seed detached and let the
    // operator/resume retry.
    if (!detached() && seeded && deps.state.maxFoldedSeq === opts.fromSeq)
      await deps.recoverLostRun();
  }

  onCleanup(() => controller?.abort());

  return {
    detached,
    reattaching,
    driveRun,
    reattachRun,
    supersede: () => {
      controller?.abort();
      controller = null;
      driveGen++; // orphan the in-flight drive's teardown
      setReattaching(false);
      setDetached(false);
    },
    stop: () => {
      controller?.abort();
      controller = null;
      setDetached(false);
    },
  };
}
