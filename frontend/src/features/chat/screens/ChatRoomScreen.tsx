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
  Drawer,
  EmptyState,
  Icon,
  InfoHint,
  Input,
  Menu,
  Modal,
  Panel,
  Stack,
  StatusFlag,
  Text,
  TypewriterText,
  confirm,
  toast,
  type MenuItem,
} from "~/ui";
import {
  REVEAL_SPEED_MS,
  consumePendingDraft,
  consumeRequestedSession,
  createChatStream,
  deleteConversation,
  entrySessionId,
  refreshSessions,
  renameConversation,
  titleReveals,
  useChatSession,
  useChatSessions,
} from "../data";
import { selectedModelLabel, setSelectedModel } from "~/lib/stores/models";
import { MessageItem } from "../components/MessageItem";
import { SessionList } from "../components/SessionList";

/** Chat room: a searchable thread rail and a live streaming conversation. On
 *  entry it resumes the last conversation only while it's warm (recency-gated),
 *  otherwise it opens a fresh composer — the overview launchpad can also hand it
 *  a thread to open or a message to start. */
export function ChatRoomScreen(): JSX.Element {
  const sessions = useChatSessions();
  // null = a new, unsaved conversation.
  const [currentId, setCurrentId] = createSignal<string | null>(null);
  const session = useChatSession(currentId);
  // While a thread's history loads, the resource still reports the *previous*
  // thread's messages (Solid retains a resource's last value across a source
  // change). Feeding that stale value to the stream would seed the outgoing
  // thread's history into the incoming one, so withhold the source until it has
  // resolved for the current id — the stream re-seeds once it arrives.
  const stream = createChatStream(
    () => (session.loading ? undefined : session()?.messages),
    currentId,
    {
      // A new thread adopts its backend id once persisted; the list refreshes so
      // the sidebar reflects the new/updated thread.
      onConversationStarted: (id) => setCurrentId(id),
      onTurnComplete: () => refreshSessions(),
    },
  );

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
          n += 1; // approval / artifact / preview: a new block is enough
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

  // Resolve the entry intent once: new-from-overview › open-specific › recency.
  const [resolved, setResolved] = createSignal(false);
  createEffect(() => {
    if (resolved()) return;
    const draft = consumePendingDraft();
    if (draft) {
      // Only adopt an explicit pick — an empty draft (discovery not yet resolved
      // on the overview) must not clobber the operator's sticky selection.
      if (draft.model) setSelectedModel(draft.model);
      setCurrentId(null);
      queueMicrotask(() => void stream.send(draft.text));
      setResolved(true);
      return;
    }
    const requested = consumeRequestedSession();
    if (requested) {
      setCurrentId(requested);
      setResolved(true);
      return;
    }
    const list = sessions();
    if (!list) return; // wait for the seam to resolve
    setCurrentId(entrySessionId(list));
    setResolved(true);
  });

  const startNew = () => setCurrentId(null);

  // Right-aligned "new conversation" control, shown beside the SESSIONS title in
  // both the desktop rail and the mobile drawer. In the desktop panel it bleeds
  // out to fill the header cell (negative margins cancel the header padding); the
  // drawer shares its header with a close button, so it stays inset there.
  const newSessionButton = (flush = false) => (
    <Button
      variant="ghost"
      size="sm"
      leading="plus"
      onClick={startNew}
      class={
        flush
          ? "-my-2 -mr-4 !h-auto self-stretch border-l border-line bg-raised"
          : "border-l border-line bg-raised"
      }
    >
      NEW
    </Button>
  );

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
  onMount(() => document.addEventListener("keydown", onKey));
  onCleanup(() => document.removeEventListener("keydown", onKey));

  // Mobile session drawer
  const [sessionsOpen, setSessionsOpen] = createSignal(false);
  const select = (id: string) => {
    setCurrentId(id);
    setSessionsOpen(false);
  };

  // Per-conversation draft key, so an unsent message is restored on return.
  const composerKey = () => `chat:${currentId() ?? "new"}`;

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

  const handleDelete = async () => {
    const id = currentId();
    if (!id) return;
    if (
      !(await confirm({
        title: "Delete this conversation?",
        detail: "This permanently removes the thread and its history.",
        confirmLabel: "DELETE",
        tone: "alert",
      }))
    )
      return;
    try {
      // Deleting a thread mid-stream must stop its generation: cancel the live
      // run first (while it still exists) so the backend halts it, rather than
      // leaving it generating into a conversation that's about to be gone —
      // aborting the local SSE alone wouldn't stop the run server-side.
      if (stream.sending()) await stream.cancel();
      await deleteConversation(id);
      startNew();
      toast.success("Conversation deleted");
    } catch {
      toast.error("Unable to delete the conversation.");
    }
  };

  return (
    <div class="flex h-full min-h-0 gap-4">
      {/* Session list — desktop sidebar */}
      <aside class="hidden w-56 shrink-0 lg:block">
        <Panel label="SESSIONS" meta={newSessionButton(true)} flush>
          <SessionList
            sessions={sessions}
            currentId={currentId()}
            onSelect={select}
          />
        </Panel>
      </aside>

      {/* Session list — mobile drawer */}
      <Drawer
        open={sessionsOpen()}
        onClose={() => setSessionsOpen(false)}
        title="SESSIONS"
        meta={newSessionButton()}
        side="left"
      >
        <SessionList
          sessions={sessions}
          currentId={currentId()}
          onSelect={select}
        />
      </Drawer>

      {/* Conversation */}
      <section class="flex min-h-full min-w-0 flex-1 flex-col">
        <header class="flex items-center justify-between gap-3 border-b border-line pb-3">
          <div class="flex min-w-0 items-center gap-2">
            {/* Mobile: sessions trigger */}
            <button
              type="button"
              class="shrink-0 text-dim transition-colors hover:text-bright lg:hidden"
              aria-label="Open sessions"
              onClick={() => setSessionsOpen(true)}
            >
              <Icon name="menu" size={16} />
            </button>
            <div class="flex min-w-0 flex-col gap-0.5">
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
              {stream.sending() ? "STREAMING" : "IDLE"}
            </StatusFlag>
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
                  icon="terminal"
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
                    onRewind={() => {
                      void stream.rewind(message.id);
                    }}
                    onDelete={async () => {
                      if (
                        await confirm({
                          title: "Delete this message?",
                          detail: "This removes it and everything after it.",
                          confirmLabel: "DELETE",
                          tone: "alert",
                        })
                      ) {
                        await stream.removeMessage(message.id);
                        toast.success("Message deleted");
                      }
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
            onSend={(text) => void stream.send(text)}
            storageKey={composerKey()}
          />
        </div>
      </section>

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
