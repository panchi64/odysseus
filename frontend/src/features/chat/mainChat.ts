/**
 * The persistent main-chat controller.
 *
 * The chat room's stream, its selected conversation, and its loaded history live here —
 * under a never-disposed root — rather than inside the screen component. Navigating away
 * and back therefore no longer tears down an in-flight turn: a run started on one visit
 * keeps streaming into this store, and re-entering the room re-binds to it instead of
 * fetching an as-yet-unpersisted (empty) thread. (A turn's messages are only persisted
 * when it finishes, so a mid-stream refetch would otherwise read an empty conversation and
 * the room would render blank.)
 *
 * The compare panes still spin up their own throwaway `createChatStream`s — only the
 * single main room is this long-lived singleton.
 *
 * **What this module owns that the stream does not:** the *binding* the operator is
 * currently pointed at. The mode comes from the app-wide mode store (the theme and the
 * shell read it too); the permission level lives here, because unlike the mode it is sent
 * on every turn and persisted per conversation, so it belongs to the thread on screen
 * rather than to the window.
 */

import {
  createEffect,
  createRoot,
  createSignal,
  on,
  onCleanup,
  type Accessor,
} from "solid-js";
import {
  setAwaitingApproval,
  setChatBusy,
  setRunErrored,
} from "~/lib/stores/chatActivity";
import { markConversationRead } from "~/lib/stores/notifications";
import {
  activeSessionMode,
  codeProjectId,
  setActiveSessionMode,
  setCodeProjectId,
} from "~/lib/stores/sessionMode";
import type { SessionMode } from "~/lib/modes";
import { useChatSession } from "./data/conversations";
import { refreshSessions } from "./data/sessions";
import { DEFAULT_PERMISSION_LEVEL, type PermissionLevel } from "./model";
import { createChatStream } from "./stream/chatStream";

export interface MainChat {
  currentId: Accessor<string | null>;
  setCurrentId: (id: string | null) => void;
  stream: ReturnType<typeof createChatStream>;
  /** Whether the one-time warm-resume entry intent has run this app session. The
   *  flag is part of the singleton so it survives navigation — see the screen. */
  warmResolved: Accessor<boolean>;
  markWarmResolved: () => void;
  /** **The mode context** — which kind of work the operator is looking at. Re-exposed
   *  from the app-wide store (`lib/stores/sessionMode`) so the chat surfaces reach it
   *  through the same handle as everything else here; a saved thread's *stored* binding
   *  stays the backend's, this is only what the client is currently pointed at. */
  mode: Accessor<SessionMode>;
  setMode: (mode: SessionMode) => void;
  codeProjectId: Accessor<string | undefined>;
  setCodeProjectId: (id: string | undefined) => void;
  /** How far the model may go in the open thread. Unlike the mode this is sent on
   *  every turn and persisted per conversation, so the composer's control moves it
   *  mid-thread; seeded from the loaded thread so a reload comes back where the
   *  operator left it, and reset to the mode's default when a new thread is
   *  staged. */
  permission: Accessor<PermissionLevel>;
  setPermission: (level: PermissionLevel) => void;
}

let _mainChat: MainChat | undefined;

/** The app-wide chat room controller — created once, then reused across mounts. */
export function mainChat(): MainChat {
  if (_mainChat) return _mainChat;
  return (_mainChat = createRoot(() => {
    const [currentId, setCurrentId] = createSignal<string | null>(null);
    const [permission, setPermission] = createSignal<PermissionLevel>(
      DEFAULT_PERMISSION_LEVEL,
    );
    const session = useChatSession(currentId);
    const stream = createChatStream(
      // Withhold the source while history loads — the resource still reports the
      // previous thread's value across a source change (Solid retains it), and
      // feeding that to the stream would seed the wrong thread.
      () => (session.loading ? undefined : session()?.messages),
      currentId,
      {
        onConversationStarted: (id) => setCurrentId(id),
        onTurnComplete: () => refreshSessions(),
        // Withheld in lockstep with the history above, so the meter seeds from the
        // loaded thread rather than the retained value of the one just left.
        initialContext: () =>
          session.loading ? undefined : session()?.context,
        // Same lockstep: the loaded thread's cumulative readout.
        initialStats: () => (session.loading ? undefined : session()?.stats),
        // Same lockstep: the in-flight run of the loaded thread, for a cold-read
        // reattach (a page reload mid-stream).
        activeRun: () => (session.loading ? undefined : session()?.activeRun),
        // Same lockstep: the loaded thread's git-style snapshot history.
        initialSnapshots: () =>
          session.loading ? undefined : session()?.snapshots,
        // Read only when a send creates the conversation.
        mode: activeSessionMode,
        projectId: codeProjectId,
        // Read on every send — the level is the one binding fact that moves.
        permission,
      },
    );
    // Opening a thread points the client at what that thread *is*: its mode moves the
    // rail and the signature accent, its level seats the composer's control. Both are
    // seeded from the load rather than left on the previous thread's values, which is
    // what stops the window from claiming to be in a code session while a normal one
    // is on screen. Staging a new thread (`currentId === null`) leaves the mode where
    // the operator put it — that choice is the whole point of the switch — and returns
    // the level to the default, since there is no thread yet to have a level.
    createEffect(() => {
      if (currentId() === null) {
        setPermission(DEFAULT_PERMISSION_LEVEL);
        return;
      }
      if (session.loading) return;
      const loaded = session();
      if (!loaded) return;
      setActiveSessionMode(loaded.mode);
      setPermission(loaded.permission);
    });
    // Reattach when the tab returns to the foreground or the network comes back.
    // A backgrounded tab throttles the SSE reader until it stalls; on return we
    // replay from the last folded seq — resuming a still-live run or folding the
    // tail of one that finished while we were away (which clears the frozen
    // streaming state via the drive's finally). No-op when nothing is in flight.
    const resume = () => {
      const runId = stream.activeRunId();
      const inFlight =
        stream.sending() || stream.messages.some((m) => m.streaming);
      if (runId && inFlight) {
        void stream.reattachRun(runId, { fromSeq: stream.lastSeq() });
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") resume();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", resume);
    onCleanup(() => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", resume);
    });
    // Mirror the main room's streaming state to the global flag the nav rail reads,
    // so the Chat item shows a live indicator while a turn runs — even from another
    // section. Only the main room drives it (compare panes are ephemeral).
    createEffect(() => setChatBusy(stream.sending()));
    // A turn *starting* changes the list as much as one finishing: each row's
    // activity edge is server-derived, so the list has to be re-read for the
    // running thread to light up. `onTurnComplete` above covers the other edge.
    createEffect(
      on(
        () => stream.sending(),
        (sending) => {
          if (sending) refreshSessions();
        },
        { defer: true },
      ),
    );
    // Same main-room-only mirror for the last-run-error echo, so the favicon can flag a
    // failed run from any screen.
    createEffect(() => setRunErrored(stream.errored()));
    // Same mirror for the awaiting-approval echo, so the nav rail and favicon can flag
    // a parked run needing a decision from any screen, not just while on /chat.
    createEffect(() => setAwaitingApproval(stream.awaitingApproval()));
    // Read-on-view: the one place a thread selection lands, regardless of whether it
    // came from the RECENTS rail, the chat screen's warm-resume, or a notification's
    // deep-link — so opening a conversation always clears its unread notifications
    // without every caller having to remember to do it.
    createEffect(() => {
      const id = currentId();
      if (id) markConversationRead(id);
    });
    const [warmResolved, setWarmResolved] = createSignal(false);
    return {
      currentId,
      setCurrentId,
      stream,
      warmResolved,
      markWarmResolved: () => setWarmResolved(true),
      mode: activeSessionMode,
      setMode: setActiveSessionMode,
      codeProjectId,
      setCodeProjectId,
      permission,
      setPermission,
    } satisfies MainChat;
  }));
}
