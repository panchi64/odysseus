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
import {
  Button,
  Composer,
  EmptyState,
  Frames,
  InfoHint,
  Input,
  Menu,
  Modal,
  ResizeHandle,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  TypewriterText,
  confirm,
  confirmChoice,
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
  mainChat,
  refreshSessions,
  renameConversation,
  regenerateTitle,
  titleReveals,
  useChatSessions,
} from "../data";
import { selectedModelLabel, setSelectedModel } from "~/lib/stores/models";
import { readLS, writeLS } from "~/lib/storage";
import { createComposerAttachments } from "~/features/uploads/data";
import { ViewportPanel } from "../components/ViewportPanel";
import { claimAutoOpen, collectViewItems } from "../viewport";
import { ContextMeter } from "../components/ContextMeter";
import { ConversationGrants } from "../components/ConversationGrants";
import { MessageItem } from "../components/MessageItem";

/** Chat room: a searchable thread rail and a live streaming conversation. On
 *  entry it resumes the last conversation only while it's warm (recency-gated),
 *  otherwise it opens a fresh composer — the overview launchpad can also hand it
 *  a thread to open or a message to start. */
export function ChatRoomScreen(): JSX.Element {
  const sessions = useChatSessions();
  // The room's stream, selected conversation (null = new, unsaved), and loaded
  // history live in a persistent module-level controller — not in this component
  // — so navigating away mid-turn and back doesn't tear down the in-flight run.
  const { currentId, setCurrentId, stream, warmResolved, markWarmResolved } =
    mainChat();

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
  // The model below the title is what this chat *last ran on* (the summary's
  // last-used model), not the top-bar picker selection — that's the picker's job.
  // A fresh thread with no answers yet falls back to the current selection, since
  // that's the model its first turn will use.
  const headerModel = () =>
    currentSummary()?.model ?? (selectedModelLabel() || "NO MODEL");

  // Resolve the entry intent: new-from-overview › open-specific › recency.
  createEffect(() => {
    // Explicit cross-surface intents (the overview launchpad) are deliberate and
    // apply on every entry — even after the one-time warm resume below.
    const draft = consumePendingDraft();
    if (draft) {
      // Only adopt an explicit pick — an empty draft (discovery not yet resolved
      // on the overview) must not clobber the operator's sticky selection.
      if (draft.model) setSelectedModel(draft.model);
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

  // ⌘/Ctrl+Shift+O starts a new conversation from anywhere, even mid-thread.
  const onKey = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
      e.preventDefault();
      startNew();
    }
  };
  onMount(() => {
    document.addEventListener("keydown", onKey);
    // The sessions list is an app-wide singleton resource (no longer refetched
    // per mount), so pull once on entry to catch any out-of-band changes — a
    // second tab, a scheduled agent — since it was last loaded.
    refreshSessions();
  });
  onCleanup(() => document.removeEventListener("keydown", onKey));

  // Viewport: a collapsible, resizable pane beside the conversation — the seam
  // where documents, live previews, and artifacts will mount. Desktop-only and
  // collapsed by default; both the open state and the dragged width persist.
  // Empty for now (the layout + mount point is the deliverable; the agent's
  // preview/artifact events route here in a later step).
  const VIEWPORT_KEY = "ody.chat.viewport";
  const VIEWPORT_W_KEY = "ody.chat.viewport.w";
  const VIEWPORT_W_DEFAULT = 384;
  const VIEWPORT_W_MIN = 320;
  const VIEWPORT_W_MAX = 760;
  const clampViewportW = (w: number) =>
    Math.min(VIEWPORT_W_MAX, Math.max(VIEWPORT_W_MIN, w));
  const [viewportOpen, setViewportOpen] = createSignal(
    readLS(VIEWPORT_KEY) === "1",
  );
  const [viewportWidth, setViewportWidth] = createSignal(
    clampViewportW(Number(readLS(VIEWPORT_W_KEY)) || VIEWPORT_W_DEFAULT),
  );
  const toggleViewport = () => {
    const next = !viewportOpen();
    setViewportOpen(next);
    writeLS(VIEWPORT_KEY, next ? "1" : "0");
  };
  // The handle is left of the (right-hand) viewport, so dragging it left widens
  // the pane — the caller negates the pointer delta. Persist only when the drag
  // settles, not on every move.
  const adjustViewportWidth = (delta: number) =>
    setViewportWidth((w) => clampViewportW(w + delta));
  const persistViewportWidth = () =>
    writeLS(VIEWPORT_W_KEY, String(viewportWidth()));
  const openViewport = () => {
    if (viewportOpen()) return;
    setViewportOpen(true);
    writeLS(VIEWPORT_KEY, "1");
  };

  // The conversation's View, derived from this thread's transcript blocks
  // (presentation-only, so it's automatically thread-scoped). The viewport renders
  // these; the transcript shows compact chips that open them here.
  const viewItems = createMemo(() =>
    collectViewItems(stream.messages, stream.snapshots()),
  );
  // Which item the viewport shows: an explicit pick, or null = follow the newest.
  const [selectedViewKey, setSelectedViewKey] = createSignal<string | null>(
    null,
  );
  // Reset the pick on thread switch so each thread follows its own newest item.
  createEffect(() => {
    currentId();
    untrack(() => setSelectedViewKey(null));
  });
  // Open a View item in the viewport — from a transcript chip or a timeline tab.
  const openViewTo = (key: string) => {
    setSelectedViewKey(key);
    openViewport();
  };
  // First-time-only auto-open: when a thread first produces a View item, open the
  // viewport once; `claimAutoOpen` is one-shot per conversation, so a later manual
  // close is respected and subsequent items update it silently.
  createEffect(() => {
    const id = currentId();
    if (id !== null && viewItems().length > 0 && claimAutoOpen(id)) {
      openViewport();
    }
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
        confirmLabel: "DELETE",
        tone: "alert",
      });
      return ok ? false : null;
    }
    const n = orphans.length;
    const choice = await confirmChoice({
      title,
      detail: `${baseDetail} ${n} image attachment${
        n > 1 ? "s" : ""
      } would be left unused — delete them too or keep them in the gallery?`,
      confirmLabel: "DELETE IMAGES",
      secondaryLabel: "KEEP IMAGES",
      cancelLabel: "CANCEL",
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

  return (
    <div class="flex h-full min-h-0">
      {/* Conversation — the thread list now lives in the app rail's RECENTS, so
          the body is free for the conversation plus the viewport pane. */}
      <section class="flex min-h-full min-w-0 flex-1 flex-col">
        <header class="flex items-center justify-between gap-3 border-b border-line pb-3">
          <div class="flex min-w-0 items-center gap-2">
            <div class="flex min-w-0 flex-col gap-0.5">
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
              <span class="flex items-center gap-1.5">
                <StatusFlag status="nominal">{headerModel()}</StatusFlag>
                <InfoHint
                  label={`Answers in this conversation are generated by ${headerModel()}. Configure models in Settings.`}
                  side="bottom"
                />
                <Text variant="micro" tone="dim">
                  · SESSION {currentId() ?? "NEW"}
                </Text>
              </span>
            </div>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <StatusFlag
              status={stream.sending() ? "info" : "idle"}
              dot={stream.sending()}
              pulse={stream.sending()}
            >
              {stream.reattaching()
                ? "RESYNCING"
                : stream.sending()
                  ? "STREAMING"
                  : "IDLE"}
            </StatusFlag>
            <Show when={stream.usage()}>
              {(usage) => <ContextMeter usage={usage()} />}
            </Show>
            <Tooltip label="VIEWPORT" side="bottom">
              <Button
                variant="ghost"
                size="sm"
                leading="eye"
                aria-label="Toggle viewport panel"
                onClick={toggleViewport}
                class="hidden lg:inline-flex"
              >
                <Show when={!viewportOpen() && viewItems().length > 0}>
                  {viewItems().length}
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
                    label: "RENAME CONVERSATION",
                    icon: "edit",
                    disabled: !currentId(),
                    onSelect: openRename,
                  },
                  {
                    label: "REGENERATE TITLE",
                    icon: "refresh",
                    disabled: !currentId(),
                    onSelect: handleRegenerateTitle,
                  },
                  {
                    label: "DELETE CONVERSATION",
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

        <ConversationGrants
          conversationId={currentId}
          revalidate={conversationGrantsRevision}
        />

        <div class="relative flex min-h-0 flex-1 flex-col">
          <div
            ref={scrollEl}
            onScroll={onScroll}
            class="min-h-0 flex-1 overflow-y-auto py-2"
          >
            <Show
              when={stream.messages.length}
              fallback={
                <EmptyState
                  icon="chat"
                  message="START A CONVERSATION"
                  hint="Ask a question, request a summary, or describe a task to begin."
                />
              }
            >
              <For each={stream.messages}>
                {(message) => (
                  <MessageItem
                    message={message}
                    onResolveApproval={stream.resolveApproval}
                    onResolveHostCommands={stream.resolveHostCommands}
                    onRegenerate={() => void stream.regenerate(message.id)}
                    onEditMessage={(id, text) => void stream.edit(id, text)}
                    onSwitchVersion={(id, i) =>
                      void stream.switchVersion(id, i)
                    }
                    onTogglePin={() => void stream.toggleMessagePin(message.id)}
                    onOpenInView={openViewTo}
                    onRewind={() => {
                      void stream.rewind(message.id);
                    }}
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
          </div>
          <Show when={showJump()}>
            <Button
              variant="default"
              size="sm"
              leading="chevron-down"
              onClick={jumpToLatest}
              class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-surface"
            >
              JUMP TO LATEST
            </Button>
          </Show>
        </div>

        <div class="sticky bottom-0 -mx-1">
          <Composer
            autofocus
            disabled={stream.sending()}
            streaming={stream.sending()}
            onStop={() => void stopRun()}
            onSend={(text, ids) => void stream.send(text, ids)}
            attachments={attachments}
            storageKey={composerKey()}
          />
        </div>
      </section>

      {/* Viewport — documents / live previews / artifacts sit here beside the
          conversation, on a draggable divider so the operator can size it to the
          content. Desktop-only; toggled from the header; empty for now. */}
      <Show when={viewportOpen()}>
        <ResizeHandle
          aria-label="Resize viewport panel"
          onResize={(dx) => adjustViewportWidth(-dx)}
          onResizeEnd={persistViewportWidth}
          class="hidden lg:block"
        />
        <aside
          class="hidden shrink-0 lg:block"
          style={{ width: `${viewportWidth()}px` }}
        >
          <ViewportPanel
            items={viewItems()}
            selectedKey={selectedViewKey()}
            onSelect={setSelectedViewKey}
            onClose={toggleViewport}
          />
        </aside>
      </Show>

      <Modal
        open={renameOpen()}
        onClose={() => setRenameOpen(false)}
        title="RENAME CONVERSATION"
      >
        <Stack gap={3}>
          <Input
            label="TITLE"
            value={renameValue()}
            onInput={(e) => setRenameValue(e.currentTarget.value)}
            placeholder="Conversation title"
          />
          <div class="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRenameOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              disabled={!renameValue().trim()}
              onClick={submitRename}
            >
              SAVE
            </Button>
          </div>
        </Stack>
      </Modal>
    </div>
  );
}
