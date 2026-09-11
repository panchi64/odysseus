import {
  Show,
  createEffect,
  createMemo,
  onMount,
  untrack,
  type JSX,
} from "solid-js";
import { Composer, cx, toast } from "~/ui";
import {
  conversationGrantsRevision,
  consumePendingDraft,
  consumeRequestedSession,
  entrySessionId,
  mainChat,
  refreshSessions,
  titleReveals,
  useChatSessions,
} from "../data";
import { sessionModeSpec } from "~/lib/modes";
import { sendBlockedReason, setSelectedModel } from "~/lib/stores/models";
import {
  activeSessionMode,
  codeProjectId,
  setCodeProjectId,
} from "~/lib/stores/sessionMode";
import { createComposerAttachments } from "~/features/uploads/data";
import { useProjects } from "~/lib/stores/projects";
import { directoryLabel, focusAddDirectory } from "../addDirectory";
import { ChatRoomHeader } from "../components/ChatRoomHeader";
import { ChatViewportMounts } from "../components/ChatViewportMounts";
import { ContextRing } from "../components/ContextRing";
import { ConversationStatusStrip } from "../components/ConversationStatusStrip";
import { ParkDock } from "../components/ParkDock";
import { PermissionControl } from "../components/PermissionControl";
import { TranscriptView } from "../components/TranscriptView";
import { ModelPicker } from "~/app/ModelPicker";
import { createConversationActions } from "../conversationActions";
import { registerChatRoomKeymap } from "../chatRoomKeymap";
import { useChatViewport } from "../useChatViewport";
import { createBranchState } from "../branchState";
import { createTranscriptFollow } from "../transcriptScroll";
import { createRenameConversation } from "../components/RenameConversationModal";

/** The conversation's reading measure. A line of text on a 27" display is
 *  unreadable at full width long before it is uncomfortable, and the composer
 *  spanning the whole bottom of the screen made the input read as a page
 *  element rather than as a thing to type into.
 *
 *  It is deliberately ONE constant applied to both the transcript's content and
 *  the composer dock. They are the same column and must agree: an input
 *  narrower than the messages above it looks like a mistake, and an input wider
 *  than them looks like two layouts. The scroll container and the dock's
 *  background still span the full width — only their contents are centred — so
 *  the scrollbar stays at the edge of the pane and the transcript still
 *  disappears behind the dock rather than beside it. */
const MEASURE = "mx-auto w-full max-w-4xl";

/** Chat room: a searchable thread rail and a live streaming conversation. On
 *  entry it resumes the last conversation only while it's warm (recency-gated),
 *  otherwise it opens a fresh composer — the overview launchpad can also hand it
 *  a thread to open or a message to start. */
export function ChatRoomScreen(): JSX.Element {
  const sessions = useChatSessions();
  // The room's stream, selected conversation (null = new, unsaved), and loaded
  // history live in a persistent module-level controller — not in this component
  // — so navigating away mid-turn and back doesn't tear down the in-flight run.
  const {
    currentId,
    setCurrentId,
    stream,
    warmResolved,
    markWarmResolved,
    permission,
    setPermission,
    permissionPending,
  } = mainChat();
  // Straight from the app-wide store, not through the room controller: the mode is
  // the window's, and re-exposing it on the chat handle only hid that.
  const mode = activeSessionMode;
  const projects = useProjects();
  /** This thread works in a directory on the operator's machine, not in a sandbox. */
  const rooted = () => sessionModeSpec(mode()).workspace === "worktree";

  /** The project a **staged** worktree thread would work in — undefined once the thread
   *  is saved, and for every sandbox mode. Read by both the send gate (which needs to
   *  know the directory can host a worktree) and the header's subtitle (which names it),
   *  so the two can't disagree about which directory is in play. */
  const stagedProject = createMemo(() => {
    if (!rooted() || currentId() !== null) return undefined;
    const id = codeProjectId();
    return id ? projects.latest?.projects.find((p) => p.id === id) : undefined;
  });

  /** Why SEND is unavailable, or null. The model/context gate, plus the one thing
   *  only this screen can know: a worktree thread is cut from a directory's repository,
   *  so a send that names no directory is a turn the backend will refuse with a 422.
   *  Saying so before the message is committed is the same courtesy the context gate
   *  already extends — the alternative is losing a typed message to an error.
   *
   *  It should now be near-unreachable: a code thread is started *from* its directory,
   *  so there is no ordinary path to a staged one with none. It stays as the backstop
   *  for the paths that don't go through the rail. */
  const sendBlocked = (): string | null => {
    if (rooted() && currentId() === null) {
      if (!codeProjectId())
        return "Choose a directory in the rail for this code session";
      // The directory is staged but cannot host a worktree. The rail's heading already
      // carries this as a marker; saying it again here is what stops a typed message
      // being spent on a turn the backend is certain to refuse.
      const project = stagedProject();
      if (project && !project.repo.isGitRepo)
        return `${project.name} isn't a git repository yet`;
    }
    return sendBlockedReason();
  };

  // Follow the stream: pinned to the bottom while the answer arrives, yielding the
  // moment the operator scrolls up to read back (see `transcriptScroll.ts`).
  const transcript = createTranscriptFollow({
    messages: stream.messages,
    sending: stream.sending,
    conversationId: currentId,
  });

  // Header reflects the selected thread (messages resolve through the seam).
  const currentSummary = createMemo(() => {
    const id = currentId();
    return id ? sessions()?.find((s) => s.id === id) : undefined;
  });
  const headerTitle = () => currentSummary()?.title ?? "New conversation";
  // A just-generated title for the open thread, if the backend named it this turn.
  const headerReveal = () => {
    const id = currentId();
    return id ? titleReveals[id] : undefined;
  };

  // Resolve the entry intent: new-from-overview › open-specific › recency.
  createEffect(() => {
    // Explicit cross-surface intents (the overview launchpad) are deliberate and
    // apply on every entry — even after the one-time warm resume below.
    const draft = consumePendingDraft();
    if (draft) {
      // Only adopt an explicit pick — an empty draft (discovery not yet resolved
      // on the overview) must not clobber the operator's sticky selection.
      if (draft.model) void setSelectedModel(draft.model);
      setCurrentId(null);
      queueMicrotask(() => void stream.send(draft.text, draft.attachmentIds));
      markWarmResolved();
      return;
    }
    const requested = consumeRequestedSession();
    if (requested) {
      setCurrentId(requested);
      markWarmResolved();
      return;
    }
    // Recency resume is a once-per-session entry concern. The room's state is now
    // persistent across navigation, so re-running it on every remount would yank
    // the operator off whatever thread (or fresh composer) they'd left open.
    if (warmResolved()) return;
    const list = sessions();
    if (!list) return; // wait for the seam to resolve
    if (untrack(currentId) === null) setCurrentId(entrySessionId(list));
    markWarmResolved();
  });

  /** The directory a staged worktree thread will work in, as the header names it.
   *  Nothing for a saved thread — its branch chip is the answer there. */
  const workspaceHint = (): string | undefined => {
    const project = stagedProject();
    return project ? directoryLabel(project) : undefined;
  };

  /** Off the open thread and onto a fresh composer. Unconditional — this is where the
   *  room goes when the thread it was showing is *gone*, so it can never decline. */
  const clearThread = () => setCurrentId(null);

  /** A fresh composer, **asked for**.
   *
   *  In a worktree mode it lands in a directory rather than nowhere, resolved in the
   *  order the operator would expect: whatever is already staged, else the directory of
   *  the thread they are standing in, else the one they opened most recently. The staged
   *  value alone is not enough to decide on — it is a memory-only signal, so it is unset
   *  after every reload, and keying the fallback on it made the reflex shortcut dead on
   *  a fresh window even with a dozen directories filed.
   *
   *  Only with genuinely nowhere to start does this decline, and then it puts the
   *  operator in front of the rail's ADD DIRECTORY button rather than raising a modal OS
   *  chooser off a keystroke they made without looking. */
  const startNew = () => {
    if (!rooted()) return clearThread();
    if (!codeProjectId()) {
      const target =
        currentSummary()?.projectId ?? projects.latest?.projects[0]?.id;
      if (!target) {
        if (focusAddDirectory()) return;
      } else setCodeProjectId(target);
    }
    clearThread();
  };

  // Stop the live run for real: cancel on the backend, abort the local stream.
  // `cancel()` surfaces its own backend error; this only adds the success note.
  const stopRun = async () => {
    if (!stream.sending()) return;
    await stream.cancel();
    toast.success("Run cancelled");
  };

  onMount(() => {
    // The sessions list is an app-wide singleton resource (no longer refetched
    // per mount), so pull once on entry to catch any out-of-band changes — a
    // second tab, a scheduled agent — since it was last loaded.
    refreshSessions();
  });

  // A code thread's branch, read once for everyone who shows it: the header's chip and
  // the Diff surface are two views of one fetch, and two resources over the same
  // endpoint would disagree for as long as either was in flight. Re-reads when a turn
  // settles, since that is when the agent has just changed something.
  const branch = createBranchState(currentId, () => (stream.sending() ? 0 : 1));

  // The viewport pane beside the conversation — everything about what it holds, how
  // wide it is, whether it renders as an aside or a sheet, and where focus goes when
  // it closes. It is a concern of its own, so it lives in one.
  const viewport = useChatViewport(currentId, {
    ...stream,
    branch: branch.latest,
    refetchBranch: branch.refetch,
    permission,
  });

  registerChatRoomKeymap({
    viewport,
    focusTranscript: () => transcript.element()?.focus(),
    startNew,
  });

  // Per-conversation draft key, so an unsent message is restored on return.
  const composerKey = () => `chat:${currentId() ?? "new"}`;

  // File attachments for the next turn. Transient (not persisted like the draft):
  // switching threads discards any still-attached files so they don't ride along
  // to a different conversation.
  const attachments = createComposerAttachments();
  createEffect(() => {
    currentId();
    untrack(() => attachments.clear());
  });

  const rename = createRenameConversation({
    conversationId: currentId,
    currentTitle: () => currentSummary()?.title,
  });

  // Retitle, fork, copy, the thread's browser and the two deletes — everything that
  // acts on the thread rather than on a turn in it.
  const actions = createConversationActions({
    conversationId: currentId,
    messages: stream.messages,
    sending: stream.sending,
    cancel: stream.cancel,
    removeMessage: stream.removeMessage,
    onDeleted: clearThread,
    onForked: setCurrentId,
  });
  // A "working" throbber sits on the title while the backend names the thread —
  // either the first-turn auto-title (stream) or a manual regenerate.
  const titleWorking = () => stream.titlePending() || actions.retitling();

  return (
    <div ref={viewport.rowRef} class="flex h-full min-h-0">
      {/* Conversation — the thread list now lives in the app rail's RECENTS, so
          the body is free for the conversation plus the viewport pane. */}
      <section class="flex min-h-full min-w-0 flex-1 flex-col">
        <ChatRoomHeader
          title={headerTitle}
          reveal={headerReveal}
          workspaceHint={workspaceHint}
          working={titleWorking}
          conversationId={currentId}
          streaming={stream.sending}
          messageCount={() => stream.messages.length}
          viewport={viewport}
          branch={branch.latest}
          actions={{
            rename: rename.open,
            retitle: () => void actions.retitle(),
            compact: () => void stream.compactNow(),
            openBrowser: () => void actions.openBrowser(),
            copy: actions.copyTranscript,
            remove: () => void actions.removeConversation(),
          }}
        />

        <TranscriptView
          stream={stream}
          viewport={viewport}
          actions={actions}
          scroll={transcript}
          conversationId={currentId}
          measure={MEASURE}
        />

        {/* The composer docks on the page background, so the transcript scrolls
            out of sight behind it instead of showing through the gap around the
            card. No rule and no gradient — just the ground, and the LED strip on
            the composer's own top edge doing the separating with light.
            **No top padding**: the strip has to BE the cutoff. Any gap above it
            is a band of bare page between the last line of the transcript and
            the light — the transcript ends, then nothing, then the composer —
            and the strip stops reading as the edge the conversation runs into.
            The glow costs no layout (it is a shadow, and nothing between here
            and the viewport clips it), so it still spills up over the transcript
            without a pad to spill into. */}
        {/* The dock's own background spans the full width — it is what the
            transcript scrolls out of sight behind — while its contents take the
            same measure as the transcript above. */}
        {/* The background is dropped while a run is parked, and only then. The park
            panel is *glass*: an opaque fill behind it leaves it nothing to frost, and
            it would read as a flat tinted card rather than as the transcript seen
            through it (see `ParkDock`). It stays full-width for the composer, which
            needs the transcript to disappear behind it rather than beside it. */}
        <div class={cx("sticky bottom-0 px-4 pb-1", !stream.park() && "bg-bg")}>
          <div class={MEASURE}>
            {/* A parked run takes the composer's place. It is the same slot, so
                nothing below the transcript moves — but the only thing offered is
                the thing the run is waiting for. */}
            <Show when={stream.park()}>
              {(park) => (
                <ParkDock
                  park={park()}
                  onStop={() => void stopRun()}
                  onSubmit={(settlement) =>
                    stream.resolvePark(park().messageId, settlement)
                  }
                />
              )}
            </Show>
            <Show when={!stream.park()}>
              <Composer
                edge="led"
                autofocus
                streaming={stream.sending()}
                onStop={() => void stopRun()}
                onSend={(text, ids) => void stream.send(text, ids)}
                // The backend refuses a turn it can't keep inside a context window; this
                // is the same stop, arriving before the message is committed to it.
                sendBlocked={sendBlocked()}
                attachments={attachments}
                storageKey={composerKey()}
                prefill={stream.undeliveredDraft()}
                onPrefillConsumed={stream.clearUndeliveredDraft}
                controls={
                  // Ungated, unlike the mode picker that used to sit here. A mode is
                  // set once at creation — a code thread owns a branch, and
                  // re-pointing it would strand that branch — so that control was
                  // only shown while a thread was unsaved, and it now lives beside
                  // the thread list. A level is the opposite: it is the operator's
                  // live control over a thread already in flight, so it is offered at
                  // every moment of one, and it rides the next send.
                  <PermissionControl
                    level={permission()}
                    onLevelChange={setPermission}
                    // While an opened thread's own level is still in flight the seat holds
                    // the strictest one as a placeholder; the control reports that rather
                    // than naming a level the thread may not be at.
                    pending={permissionPending()}
                  />
                }
                trailing={
                  <>
                    {/* Where the message is going, then how full the thread it's
                      going into is — both read on the way to SEND. */}
                    <ModelPicker />
                    {/* Only once a run has reported. The ring used to be
                      unconditional and paint an alert-toned "context window
                      unknown" whenever it had nothing — which on a brand-new
                      thread is simply *before the first turn*, so a fresh chat
                      opened on a red gauge announcing a fault that had not been
                      established. A gauge with nothing to measure has nothing to
                      say. The genuinely-unknown case is not lost: it is the send
                      gate's, which blocks SEND and explains why. */}
                    <Show when={stream.usage()}>
                      {(usage) => (
                        <ContextRing
                          usage={usage()}
                          lastRequest={stream.stats()?.lastRequest}
                        />
                      )}
                    </Show>
                  </>
                }
              />
            </Show>
            {/* The conversation's readouts sit UNDER the input, not above the
              transcript where they used to. Two reasons, and the second is the
              one that matters: after typing, this is where the operator's eye
              already is — and docked here the line stays put while the
              conversation scrolls behind it, so nothing it says ever belongs to
              the turn that happens to be passing behind it. */}
            {/* Its own fill, because the wrapper's is gone while a park is up and
                the strip is not part of the glass — without this it would sit on the
                transcript scrolling behind it. */}
            <div class="bg-bg">
              <ConversationStatusStrip
                conversationId={currentId}
                streaming={stream.sending}
                detached={stream.detached}
                stats={stream.stats}
                plan={stream.plan}
                grantsRevalidate={conversationGrantsRevision}
              />
            </div>
          </div>
        </div>
      </section>

      {/* Documents / live previews / artifacts sit beside the conversation, on a
          draggable divider above `lg` and in a full-screen sheet below it. */}
      <ChatViewportMounts viewport={viewport} />

      {rename.element}
    </div>
  );
}
