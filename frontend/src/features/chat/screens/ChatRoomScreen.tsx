import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
  untrack,
  type JSX,
} from "solid-js";
import { Portal } from "solid-js/web";
import {
  Button,
  Composer,
  ConstructionReveal,
  EmptyState,
  ErrorBoundary,
  Frames,
  Input,
  Menu,
  Modal,
  ResizeHandle,
  Reveal,
  Stack,
  Text,
  Tooltip,
  TypewriterText,
  confirm,
  confirmChoice,
  copyToClipboard,
  toast,
  type MenuItem,
} from "~/ui";
import {
  REVEAL_SPEED_MS,
  consumePendingDraft,
  consumeRequestedSession,
  conversationGrantsRevision,
  deleteConversation,
  entrySessionId,
  fetchOrphanImageAttachments,
  forkConversation,
  mainChat,
  refreshSessions,
  renameConversation,
  regenerateTitle,
  titleReveals,
  useChatSessions,
} from "../data";
import { isApiError } from "~/lib/api";
import { sendBlockedReason, setSelectedModel } from "~/lib/stores/models";
import { createComposerAttachments } from "~/features/uploads/data";
import { BrowserPanel } from "../components/BrowserPanel";
import { ViewportPanel } from "../components/ViewportPanel";
import { BranchChip } from "../components/BranchChip";
import { ModeControl } from "../components/ModeControl";
import { ContextRing } from "../components/ContextRing";
import { ModelPicker } from "~/app/ModelPicker";
import { claimAutoOpen, collectViewItems, type ViewItem } from "../viewport";
import { assembleTranscript } from "../blocks";
import type { ChatMessage } from "../model";
import {
  activeDownload,
  clampWidth,
  downloadBlob,
  setViewerWidth,
  useViewerPersistence,
  viewerWidth,
} from "../viewerPersistence";
import { registerKeymap } from "~/lib/keymap";
import { ConversationStatusStrip } from "../components/ConversationStatusStrip";
import { MessageItem } from "../components/MessageItem";

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

/** Flatten the whole thread to plain text for COPY CONVERSATION — each turn's
 *  role and content in order, assistant turns including their tool calls/
 *  results via `assembleTranscript` (same shaping as per-message COPY
 *  MESSAGE), separated by rules so the export reads as a transcript. */
function buildConversationTranscript(messages: ChatMessage[]): string {
  return messages
    .map((m) => {
      // A compaction divider is neither party's words — label it as the chassis note it
      // is rather than attributing the summary to the assistant.
      const label =
        m.role === "user"
          ? "Operator"
          : m.role === "compaction"
            ? "Context compacted"
            : "Assistant";
      const body =
        m.role === "assistant" ? assembleTranscript(m.blocks) : m.content;
      return `${label} · ${m.createdAt}\n${body}`;
    })
    .join("\n\n---\n\n");
}

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
    mode,
    setMode,
    codingProjectId,
    setCodingProjectId,
  } = mainChat();

  // Follow the stream: keep the transcript pinned to the bottom while the answer
  // arrives, yield the moment the operator scrolls up to read back, and re-attach
  // when they scroll near the bottom again. A floating control jumps back down
  // once they've scrolled far up.
  let scrollEl: HTMLDivElement | undefined;
  const [pinned, setPinned] = createSignal(true);
  const [showJump, setShowJump] = createSignal(false);
  const scrollToBottom = () => {
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
  };
  const jumpToLatest = () => {
    setPinned(true);
    setShowJump(false);
    queueMicrotask(scrollToBottom);
  };
  const onScroll = () => {
    if (!scrollEl) return;
    const distance =
      scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
    setPinned(distance < 80); // within 80px counts as attached
    setShowJump(distance > 240); // surface the jump control past ~one screenful
  };
  // Ticks on every fragment that grows the in-flight turn — answer + reasoning
  // tokens, tool args/result/status, and host-command output — so the follow
  // effect re-runs as content streams in, not only when a message is added.
  const streamTick = createMemo(() => {
    const last = stream.messages[stream.messages.length - 1];
    if (!last) return stream.messages.length;
    let n = stream.messages.length + (last.content?.length ?? 0);
    for (const b of last.blocks ?? []) {
      switch (b.kind) {
        case "thinking":
        case "text":
          n += b.text.length;
          break;
        case "tool":
          n +=
            b.tool.status.length +
            b.tool.args.length +
            (b.tool.result?.length ?? 0) +
            (b.tool.error?.length ?? 0);
          break;
        case "host_command":
          n +=
            b.command.phase.length +
            (b.command.stdout?.length ?? 0) +
            (b.command.stderr?.length ?? 0);
          break;
        default:
          n += 1; // approval / view chips: a new block is enough
      }
    }
    return n;
  });
  createEffect(() => {
    streamTick();
    // untrack(pinned): only new content drives a scroll, so re-attaching by
    // scrolling down doesn't itself snap — the next fragment catches up.
    if (untrack(pinned)) queueMicrotask(scrollToBottom);
  });
  // The operator initiating a turn (send / regenerate / edit) re-attaches the
  // follow, so the new answer is tracked even if they had scrolled up.
  let wasSending = false;
  createEffect(() => {
    const sending = stream.sending();
    if (sending && !wasSending) jumpToLatest();
    wasSending = sending;
  });
  // Switching threads re-attaches and jumps to the latest message.
  createEffect(() => {
    currentId();
    jumpToLatest();
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
  // Everything before the newest compaction divider is still in the transcript but
  // out of what the model replays. The transcript is the only place that knows a
  // turn's position relative to the fold, so the dim pass is derived here and handed
  // down — presentation only; the backend decided what it folded.
  const foldedThrough = createMemo(() => {
    let last = -1;
    stream.messages.forEach((m, i) => {
      if (m.role === "compaction") last = i;
    });
    return last;
  });

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

  const startNew = () => setCurrentId(null);

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

  // Viewport: a collapsible, resizable pane beside the conversation (or, below
  // `lg` / in fullscreen, a full-screen sheet) — the seam where documents, live
  // previews, and artifacts mount. The dragged width is a genuine cross-thread
  // preference (global); every other preference (open, pinned version,
  // PREVIEW/CODE tab, font size, wrap, fullscreen, seen count) is **per
  // conversation**, via the shared `useViewerPersistence` seam — a manual close
  // on one thread must not be undone by a different thread's auto-open.
  const conversationKey = () => currentId() ?? "new";
  const { state, patch } = useViewerPersistence(conversationKey);

  // The conversation's View, derived from this thread's transcript blocks
  // (presentation-only, so it's automatically thread-scoped). The viewport renders
  // these; the transcript shows compact chips that open them here.
  const viewItems = createMemo(() =>
    collectViewItems(stream.messages, stream.snapshots()),
  );
  // The viewport only makes sense with something to show. Gate the effective open
  // state on having items so a persisted-open thread that's since lost its items
  // (or a fresh chat that never had any) never shows an empty panel.
  // What the panel has to show: the thread's View versions, or a live agent browser.
  // The browser is not a View item — it has no version, no code and no history — so it
  // has to be counted here or the slot would stay shut through a whole browsing session.
  const hasPanelContent = () =>
    viewItems().length > 0 || stream.browserStream() !== null;
  const viewportShown = () => state().open && hasPanelContent();
  const toggleViewport = () => {
    patch({ open: !state().open });
  };
  const openViewport = () => {
    if (!state().open) patch({ open: true });
  };
  // The aside's width while dragging: updated per pointermove tick (in-memory
  // only) so the drag never writes localStorage on every move; `setViewerWidth`
  // (the persisting setter) is only called once the drag settles, on
  // `onResizeEnd`. Seeded from the persisted global width.
  const [liveWidth, setLiveWidth] = createSignal(viewerWidth());
  // The newest version's key (the one collectViewItems flags as latest). Following
  // it (pinnedKey null) means freshly-minted versions keep advancing the view
  // instead of leaving it stranded on a now-stale pick.
  const latestViewKey = (): string | null =>
    viewItems().find((i) => i.isLatest)?.key ?? null;
  // The item actually shown: the pin if still present, else the newest.
  const resolvedViewKey = (): string | null =>
    state().pinnedKey ?? latestViewKey();

  const requestPin = (key: string | null) => patch({ pinnedKey: key });
  const requestTab = (tab: "preview" | "code") => patch({ activeTab: tab });
  // Pin a version — except picking the current latest clears the pin (null), so the
  // viewport resumes following new versions as the agent mints them.
  const selectView = (key: string) =>
    requestPin(key === latestViewKey() ? null : key);
  // Open a View item in the viewport — from a transcript chip or a timeline tab.
  const openViewTo = (key: string) => {
    selectView(key);
    openViewport();
  };
  // First-time-only auto-open: when a thread first produces a View item, open the
  // viewport once; `claimAutoOpen` is one-shot per conversation, so a later manual
  // close is respected and subsequent items update it silently.
  createEffect(() => {
    const id = currentId();
    if (id !== null && hasPanelContent() && claimAutoOpen(id)) {
      openViewport();
    }
  });
  // The badge on the header eye toggle: items minted after the "seen through"
  // pointer (`seenKey`). Counting from a key's position — not a raw count —
  // means a rewind that shrinks the list and a later regrow past the old count
  // can't coincidentally read as "seen"; a dropped key (rewound away) resolves
  // to index -1, i.e. nothing seen. Cleared (advanced to the newest key)
  // whenever the panel is visible and following the latest — a pinned older
  // version leaves later unseen items counted until the operator returns to
  // following latest.
  const unseenCount = () => {
    const items = viewItems();
    const idx = items.findIndex((i) => i.key === state().seenKey);
    return Math.max(0, items.length - (idx + 1));
  };
  createEffect(() => {
    if (viewportShown() && state().pinnedKey === null) {
      const latest = viewItems().at(-1)?.key ?? null;
      if (latest !== null && state().seenKey !== latest)
        patch({ seenKey: latest });
    }
  });

  // The panel renders in a desktop-only aside above `lg`; below it (or in
  // fullscreen at any width) it renders in a full-screen sheet instead.
  const [isDesktop, setIsDesktop] = createSignal(true);
  onMount(() => {
    const mq = window.matchMedia("(min-width: 64rem)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    onCleanup(() => mq.removeEventListener("change", update));
  });
  const sheetOpen = () =>
    viewportShown() && (state().fullscreen || !isDesktop());
  const asideOpen = () => viewportShown() && !sheetOpen();
  let sheetTrigger: HTMLButtonElement | undefined;
  const closeSheet = () => {
    if (isDesktop()) patch({ fullscreen: false });
    else patch({ fullscreen: false, open: false });
    sheetTrigger?.focus();
  };

  // Focus: the panel container (either mount) and the transcript scroll
  // container are the two jump targets for mod+shift+u; the panel-scoped
  // bindings below fire only while focus is inside the panel container.
  const [panelEl, setPanelEl] = createSignal<HTMLDivElement>();
  const panelHasFocus = () => {
    const el = panelEl();
    return el !== undefined && el.contains(document.activeElement);
  };
  // Any *other* portal-rendered dialog (the rename Modal, an attachment
  // Lightbox) already owns Esc — back off so this registry doesn't double-handle.
  const otherDialogOpen = () =>
    document.querySelector(
      '[role="dialog"][aria-modal="true"]:not([data-view-sheet])',
    ) !== null;

  const pinPrev = () => {
    const items = viewItems();
    if (items.length === 0) return;
    const idx = items.findIndex((i) => i.key === resolvedViewKey());
    // A missing key (a persisted pin whose version no longer exists) follows
    // latest, same as pinNext's fallback — so "previous" steps back from the
    // newest item instead of jumping to the oldest.
    const effIdx = idx === -1 ? items.length - 1 : idx;
    const target = items[Math.max(0, effIdx - 1)];
    if (target) selectView(target.key);
  };
  const pinNext = () => {
    const items = viewItems();
    if (items.length === 0) return;
    const idx = items.findIndex((i) => i.key === resolvedViewKey());
    if (idx === -1 || idx >= items.length - 1) requestPin(null);
    else selectView(items[idx + 1].key);
  };
  const triggerActiveDownload = () => {
    const d = activeDownload();
    if (!d) return;
    void (async () => downloadBlob(d.name, await d.getBlob()))();
  };
  // Flip the shown snapshot's keeper bookmark. Relays to the backend; the stream
  // store applies the optimistic update and reverts on failure.
  const toggleKeeper = (item: ViewItem) => {
    if (item.snapshot)
      void stream.toggleSnapshotKeeper(item.snapshot.snapshotId, !item.keeper);
  };

  registerKeymap(() => [
    // ⌘/Ctrl+Shift+O starts a new conversation from anywhere, even mid-thread.
    { combo: "mod+shift+o", run: startNew },
    { combo: "mod+shift+v", run: toggleViewport },
    {
      combo: "mod+shift+u",
      when: () => viewportShown(),
      run: () => {
        if (panelHasFocus()) scrollEl?.focus();
        else panelEl()?.focus();
      },
    },
    {
      combo: "p",
      when: panelHasFocus,
      run: () =>
        requestTab(state().activeTab === "preview" ? "code" : "preview"),
    },
    { combo: "[", when: panelHasFocus, run: pinPrev },
    { combo: "]", when: panelHasFocus, run: pinNext },
    {
      combo: "f",
      when: panelHasFocus,
      run: () => patch({ fullscreen: !state().fullscreen }),
    },
    { combo: "d", when: panelHasFocus, run: triggerActiveDownload },
    {
      combo: "escape",
      when: () => panelHasFocus() && !otherDialogOpen(),
      run: () => {
        if (sheetOpen()) closeSheet();
        else scrollEl?.focus();
      },
    },
  ]);

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

  // Rename
  const [renameOpen, setRenameOpen] = createSignal(false);
  const [renameValue, setRenameValue] = createSignal("");
  const openRename = () => {
    setRenameValue(currentSummary()?.title ?? "");
    setRenameOpen(true);
  };
  const submitRename = async () => {
    const id = currentId();
    if (!id) return;
    const title = renameValue().trim();
    if (!title) return;
    setRenameOpen(false);
    try {
      await renameConversation(id, title);
      toast.success("Conversation renamed");
    } catch {
      toast.error("Unable to rename the conversation.");
    }
  };

  const [retitling, setRetitling] = createSignal(false);
  // A "working" throbber sits on the title while the backend names the thread —
  // either the first-turn auto-title (stream) or a manual regenerate.
  const titleWorking = () => stream.titlePending() || retitling();
  const handleRegenerateTitle = async () => {
    const id = currentId();
    if (!id || retitling()) return;
    setRetitling(true);
    try {
      await regenerateTitle(id);
      toast.success("Title regenerated");
    } catch {
      toast.error("Unable to regenerate the title.");
    } finally {
      setRetitling(false);
    }
  };

  /** Open a new conversation carrying history up to this turn.
   *
   *  The backend returns the *fork's* detail, so this reseats the room onto the
   *  new id rather than reloading the source and hunting for it. The source
   *  thread is untouched, which is the whole point — a tangent shouldn't cost the
   *  conversation it came from. */
  const forkFromHere = async (messageId: string): Promise<void> => {
    const id = currentId();
    if (!id) return;
    try {
      setCurrentId(await forkConversation(id, messageId));
      toast.success("Forked into a new conversation.");
    } catch (err) {
      toast.error(
        isApiError(err) ? err.detail : "Unable to fork this conversation.",
      );
    }
  };

  // Gate a delete that may strand image attachments. Probes the backend for the
  // images this delete would orphan; if any, raises the 3-way keep/purge prompt,
  // otherwise the plain confirm. Returns the chosen `purgeImages`, or null to
  // abort. A failed probe falls back to the plain confirm (keep images) so the
  // delete stays usable.
  const resolveDeleteChoice = async (
    conversationId: string,
    title: string,
    baseDetail: string,
    messageId?: string,
  ): Promise<boolean | null> => {
    let orphans: string[] = [];
    try {
      orphans = await fetchOrphanImageAttachments(conversationId, messageId);
    } catch {
      // Probe failed — fall through to the plain confirm below.
    }
    if (orphans.length === 0) {
      const ok = await confirm({
        title,
        detail: baseDetail,
        confirmLabel: "Delete",
        tone: "alert",
      });
      return ok ? false : null;
    }
    const n = orphans.length;
    const choice = await confirmChoice({
      title,
      detail: `${baseDetail} ${n} image attachment${
        n > 1 ? "s" : ""
      } would be left unused — delete them too, or keep them?`,
      confirmLabel: "Delete images",
      secondaryLabel: "Keep images",
      cancelLabel: "Cancel",
      tone: "alert",
    });
    if (choice === "cancel") return null;
    return choice === "primary";
  };

  const handleDelete = async () => {
    const id = currentId();
    if (!id) return;
    const purgeImages = await resolveDeleteChoice(
      id,
      "Delete this conversation?",
      "This permanently removes the thread and its history.",
    );
    if (purgeImages === null) return;
    try {
      // Deleting a thread mid-stream must stop its generation: cancel the live
      // run first (while it still exists) so the backend halts it, rather than
      // leaving it generating into a conversation that's about to be gone —
      // aborting the local SSE alone wouldn't stop the run server-side.
      if (stream.sending()) await stream.cancel();
      await deleteConversation(id, purgeImages);
      startNew();
      toast.success("Conversation deleted");
    } catch {
      toast.error("Unable to delete the conversation.");
    }
  };

  const handleCopyConversation = () => {
    copyToClipboard(
      buildConversationTranscript(stream.messages),
      "Conversation",
    );
  };

  // The panel's JSX is defined once and placed conditionally in either the
  // desktop aside or the fullscreen sheet (never both at once — only one Show
  // branch mounts at a time), so the panel's own state never runs twice.
  // `onClose` is passed in per mount site: the aside's own Collapse just
  // toggles the panel, but the sheet's Collapse (routed through the same
  // ViewActionRow) must reset `fullscreen` and return focus to the trigger —
  // `closeSheet` does both, `toggleViewport` does neither.
  // While the agent has a live browser, it takes the slot. A browser is a place the
  // agent *is*, not an artifact it produced, so it gets none of the View's version
  // chrome — and it is transient, so the versioned View comes straight back when the
  // session ends rather than the operator having to switch back to it.
  const renderPanel = (onClose: () => void) => (
    <Show when={stream.browserStream()} fallback={renderViewportPanel(onClose)}>
      {(path) => (
        <BrowserPanel
          streamPath={path()}
          onEnded={stream.clearBrowserStream}
          fullscreen={state().fullscreen}
          onToggleFullscreen={() => patch({ fullscreen: !state().fullscreen })}
          onClose={onClose}
          panelRef={setPanelEl}
        />
      )}
    </Show>
  );

  const renderViewportPanel = (onClose: () => void) => (
    <ViewportPanel
      items={viewItems()}
      selectedKey={state().pinnedKey}
      onSelect={selectView}
      activeTab={state().activeTab}
      onSelectTab={requestTab}
      fontStep={state().fontStep}
      onFontStep={(step) => patch({ fontStep: step })}
      softWrap={state().softWrap}
      onToggleWrap={() => patch({ softWrap: !state().softWrap })}
      fullscreen={state().fullscreen}
      onToggleFullscreen={() => patch({ fullscreen: !state().fullscreen })}
      onClose={onClose}
      onKeeper={toggleKeeper}
      panelRef={setPanelEl}
    />
  );

  return (
    <div class="flex h-full min-h-0">
      {/* Conversation — the thread list now lives in the app rail's RECENTS, so
          the body is free for the conversation plus the viewport pane. */}
      <section class="flex min-h-full min-w-0 flex-1 flex-col">
        {/* Title only. The model this chat runs on is named on every assistant turn
            and picked in the app top bar; a third, read-only copy here was the one
            that read as a control. Everything else that stood in this row is in the
            status strip below it. */}
        <header class="flex items-center justify-between gap-3 pb-3">
          <span class="flex min-w-0 items-center gap-1.5">
            <Show
              when={headerReveal()}
              fallback={
                <Text variant="readout" tone="bright">
                  {headerTitle()}
                </Text>
              }
            >
              {(title) => (
                <TypewriterText
                  variant="readout"
                  tone="bright"
                  text={title()}
                  speed={REVEAL_SPEED_MS}
                />
              )}
            </Show>
            <Show when={titleWorking()}>
              <Frames class="shrink-0 text-info" />
            </Show>
          </span>
          <div class="flex shrink-0 items-center gap-2">
            {/* A coding thread's branch and diffstat. Renders nothing for a chat
                thread — the backend answers 404 for one, which is the ordinary
                case. Re-reads when a turn settles, since that is when the agent
                has just changed something. */}
            <Show when={currentId()}>
              {(id) => (
                <BranchChip
                  conversationId={id()}
                  revision={() => (stream.sending() ? 0 : 1)}
                />
              )}
            </Show>
            {/* `md`, matching the session-actions trigger beside it — these are
                peer controls in the same row and the two most-reached-for things
                in the header, so they get the same target. The rest of the
                product's ghost icon buttons stay `sm`; this row is deliberately
                the exception, not the new default. */}
            <Tooltip label="Viewport" side="bottom">
              <Button
                ref={(el) => (sheetTrigger = el)}
                variant="ghost"
                leading="eye"
                aria-label="Toggle viewport panel"
                onClick={toggleViewport}
                disabled={!hasPanelContent()}
                class={hasPanelContent() ? undefined : "hidden lg:inline-flex"}
              >
                <Show when={unseenCount() > 0}>
                  {unseenCount() > 9 ? "9+" : unseenCount()}
                </Show>
              </Button>
            </Tooltip>
            <Menu
              trigger={
                <Button variant="ghost" aria-label="Session actions">
                  ···
                </Button>
              }
              items={
                [
                  {
                    label: "Rename conversation",
                    icon: "edit",
                    disabled: !currentId(),
                    onSelect: openRename,
                  },
                  {
                    label: "Regenerate title",
                    icon: "refresh",
                    disabled: !currentId(),
                    onSelect: handleRegenerateTitle,
                  },
                  {
                    label: "Compact now",
                    icon: "layers",
                    // Nothing to fold in an empty or one-turn thread; the backend
                    // refuses those anyway, this just doesn't offer the action.
                    disabled: !currentId() || stream.messages.length < 3,
                    onSelect: () => void stream.compactNow(),
                  },
                  {
                    label: "Copy conversation",
                    icon: "copy",
                    disabled: stream.messages.length === 0,
                    onSelect: handleCopyConversation,
                  },
                  {
                    label: "Delete conversation",
                    icon: "trash",
                    danger: true,
                    disabled: !currentId(),
                    onSelect: handleDelete,
                  },
                ] satisfies MenuItem[]
              }
            />
          </div>
        </header>

        <div class="relative flex min-h-0 flex-1 flex-col">
          <div
            ref={scrollEl}
            tabindex={-1}
            onScroll={onScroll}
            /* `px-4` is not cosmetic: a scroll container clips at its padding
               box, so this is the room the live rail's LED bloom spills into.
               Without it the glow is cut off a few pixels from the rule and
               reads as a hard-edged coloured border again.

               The bright focus outline is gone — the shell's neutral focus halo
               covers this, and a white rule around the transcript was exactly
               the kind of border the system dropped.

               PADDING IS TOP-ONLY. A bottom pad here is a band of bare page
               between the last turn and the composer's LED strip, which is the
               one thing the dock below is built not to have — see its comment.
               The last turn's own `py-4` is the breathing room down there; this
               was stacking a second gap on top of it. */
            class="min-h-0 flex-1 overflow-y-auto px-4 pt-2 outline-none transition-colors"
          >
            {/* The measure goes on the CONTENT, not on the scroll container:
                the container has to keep its full width so its scrollbar sits
                at the edge of the pane and its `px-4` still gives the live
                rail's LED bloom somewhere to spill. */}
            <div class={MEASURE}>
              {/* One malformed block must not cost the operator the composer,
                  the thread list, or the text they were typing — scope a throw
                  in the message tree to the scroll region. Switching threads
                  resets it. */}
              <ErrorBoundary
                message="This conversation failed to render"
                resetKey={currentId}
              >
                <Show
                  when={stream.messages.length}
                  fallback={
                    <EmptyState
                      icon="chat"
                      message="Start a conversation"
                      hint="Ask a question, request a summary, or describe a task to begin."
                    />
                  }
                >
                  <For each={stream.messages}>
                    {(message, index) => (
                      <MessageItem
                        message={message}
                        dimmed={index() < foldedThrough()}
                        onResolveApproval={stream.resolveApproval}
                        onResolveHostCommands={stream.resolveHostCommands}
                        onRegenerate={() => void stream.regenerate(message.id)}
                        onContinue={() => void stream.continueTurn(message.id)}
                        onEditMessage={(id, text) => void stream.edit(id, text)}
                        onSwitchVersion={(id, i) =>
                          void stream.switchVersion(id, i)
                        }
                        onTogglePin={() =>
                          void stream.toggleMessagePin(message.id)
                        }
                        onWithdraw={() => {
                          if (message.queuedMessageId)
                            void stream.withdrawQueued(message.queuedMessageId);
                        }}
                        onEditQueued={(text) => {
                          if (message.queuedMessageId)
                            void stream.editQueued(
                              message.queuedMessageId,
                              text,
                            );
                        }}
                        onOpenInView={openViewTo}
                        viewItems={viewItems}
                        seenKey={() => state().seenKey}
                        onReattach={() => {
                          if (message.runId)
                            void stream.reattachRun(message.runId, {
                              fromSeq: stream.lastSeq(),
                            });
                        }}
                        onRewind={() => {
                          void stream.rewind(message.id);
                        }}
                        onFork={() => void forkFromHere(message.id)}
                        onDelete={async () => {
                          const id = currentId();
                          if (!id) return;
                          const purgeImages = await resolveDeleteChoice(
                            id,
                            "Delete this message?",
                            "This removes it and everything after it.",
                            message.id,
                          );
                          if (purgeImages === null) return;
                          await stream.removeMessage(message.id, purgeImages);
                          toast.success("Message deleted");
                        }}
                      />
                    )}
                  </For>
                </Show>
              </ErrorBoundary>
            </div>
          </div>
          <Show when={showJump()}>
            <Button
              variant="default"
              size="sm"
              leading="chevron-down"
              onClick={jumpToLatest}
              class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-surface"
            >
              Jump to latest
            </Button>
          </Show>
        </div>

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
        <div class="sticky bottom-0 bg-bg px-4 pb-1">
          <div class={MEASURE}>
            <Composer
              edge="led"
              autofocus
              streaming={stream.sending()}
              onStop={() => void stopRun()}
              onSend={(text, ids) => void stream.send(text, ids)}
              // The backend refuses a turn it can't keep inside a context window; this
              // is the same stop, arriving before the message is committed to it.
              sendBlocked={sendBlockedReason()}
              attachments={attachments}
              storageKey={composerKey()}
              prefill={stream.undeliveredDraft()}
              onPrefillConsumed={stream.clearUndeliveredDraft}
              controls={
                // Only while the thread is still unsaved: the binding is set once,
                // at creation, and an existing coding thread shows its branch in the
                // status strip instead.
                <Show when={currentId() === null}>
                  <ModeControl
                    mode={mode()}
                    onModeChange={setMode}
                    projectId={codingProjectId()}
                    onProjectChange={setCodingProjectId}
                  />
                </Show>
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
                    {(usage) => <ContextRing usage={usage()} />}
                  </Show>
                </>
              }
            />
            {/* The conversation's readouts sit UNDER the input, not above the
              transcript where they used to. Two reasons, and the second is the
              one that matters: after typing, this is where the operator's eye
              already is — and docked here the line stays put while the
              conversation scrolls behind it, so nothing it says ever belongs to
              the turn that happens to be passing behind it. */}
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
      </section>

      {/* Viewport — documents / live previews / artifacts sit here beside the
          conversation, on a draggable divider so the operator can size it to the
          content. Above `lg` it's a resizable aside; below `lg` (or in
          fullscreen at any width) the same panel renders in a full-screen sheet
          instead. */}
      {/* The whole panel resolves in and dissolves out at its full width — it
          does not grow or shrink. An *animation*, not a transition, and the
          difference is the mechanism rather than taste: a transition needs a
          previous computed value, and a region that mounts the instant it is
          opened has none, so it appears at its end state. An animation has its
          own start, so it plays on mount. That is the whole reason the sheet
          always faded correctly and the aside never did.

          `ConstructionReveal` rather than `Reveal`: the View is a region the
          operator deliberately opens, so it is *built* — a `+` splits, travels
          the top edge, drops down the sides, and the glass resolves inside the
          frame it just described. A fade would say the panel had always been
          there and the light had merely come up.

          The breakpoint lives on a wrapper so the `lg:contents` leaves the
          reveal as a direct flex child of the row. */}
      <div class="hidden lg:contents">
        {/* The handle sits OUTSIDE the construction reveal, on its own gate. It
            rides the same signal so the two arrive and leave together, but
            keeping it out is what lets the frame measure the panel itself —
            inside, the marks would be offset by the handle's own width.
            A hairline splitter has no frame to draw, so a plain reveal is the
            whole of what it needs.

            `divider="hover"` because the panel already brackets itself: at rest
            the frame's left rule is the edge, and the splitter only paints when
            the operator reaches for it. */}
        <Reveal when={asideOpen()} class="flex h-full shrink-0">
          <ResizeHandle
            aria-label="Resize viewport panel"
            divider="hover"
            onResize={(dx) => setLiveWidth((w) => clampWidth(w - dx))}
            onResizeEnd={() => setViewerWidth(liveWidth())}
          />
        </Reveal>
        <ConstructionReveal
          when={asideOpen()}
          class="h-full shrink-0"
          contentClass="h-full"
        >
          <aside class="min-w-0 shrink-0" style={{ width: `${liveWidth()}px` }}>
            {renderPanel(toggleViewport)}
          </aside>
        </ConstructionReveal>
      </div>

      {/* The sheet is an overlay, so it has no space to give back — it is built
          and taken apart in place, on the same choreography as the aside.

          This is the one place the backdrop blur genuinely earns itself: the
          sheet sits directly over the transcript, so there is real content
          behind it to frost. The dialog carries the glass rather than an opaque
          `bg-bg`, which is what lets the conversation stay faintly legible
          underneath — the panel inside it is on the same surface and needs no
          fill of its own. */}
      <Portal>
        <ConstructionReveal
          when={sheetOpen()}
          class="fixed inset-0 z-50"
          contentClass="h-full"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="view-sheet-title"
            data-view-sheet
            /* No fill of its own — the frosted surface is the framed region
               `ConstructionReveal` draws, and a second glass layer here would
               stack with it and paint the transcript out. */
            class="flex h-full flex-col"
          >
            <header class="flex items-center gap-3 px-4 py-3">
              <Button
                variant="ghost"
                size="sm"
                leading="chevron-left"
                onClick={closeSheet}
              >
                Back to chat
              </Button>
              <span id="view-sheet-title">
                <Text variant="label" tone="bright">
                  View
                </Text>
              </span>
            </header>
            <div class="min-h-0 flex-1">{renderPanel(closeSheet)}</div>
          </div>
        </ConstructionReveal>
      </Portal>

      <Modal
        open={renameOpen()}
        onClose={() => setRenameOpen(false)}
        title="Rename conversation"
      >
        <Stack gap={3}>
          <Input
            label="Title"
            value={renameValue()}
            onInput={(e) => setRenameValue(e.currentTarget.value)}
            placeholder="Conversation title"
          />
          <div class="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRenameOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!renameValue().trim()}
              onClick={submitRename}
            >
              Save
            </Button>
          </div>
        </Stack>
      </Modal>
    </div>
  );
}
