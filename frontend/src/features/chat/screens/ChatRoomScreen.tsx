import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
  type JSX,
} from "solid-js";
import {
  Button,
  Composer,
  Drawer,
  EmptyState,
  Icon,
  InfoHint,
  Menu,
  Panel,
  StatusFlag,
  Text,
  confirm,
  toast,
  type MenuItem,
} from "~/ui";
import {
  consumePendingDraft,
  consumeRequestedSession,
  createChatStream,
  entrySessionId,
  selectedModel,
  setSelectedModel,
  useChatSession,
  useChatSessions,
} from "../data";
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
  const stream = createChatStream(() => session()?.messages, currentId);

  // Header reflects the selected thread (messages resolve through the seam).
  const currentSummary = createMemo(() => {
    const id = currentId();
    return id ? sessions()?.find((s) => s.id === id) : undefined;
  });
  const headerTitle = () => currentSummary()?.title ?? "New conversation";
  const headerModel = () => currentSummary()?.model ?? selectedModel();

  // Resolve the entry intent once: new-from-overview › open-specific › recency.
  const [resolved, setResolved] = createSignal(false);
  createEffect(() => {
    if (resolved()) return;
    const draft = consumePendingDraft();
    if (draft) {
      setSelectedModel(draft.model);
      setCurrentId(null);
      queueMicrotask(() => stream.send(draft.text));
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

  const handleDeleteLast = async () => {
    const last = stream.messages[stream.messages.length - 1];
    if (!last) return;
    const label =
      last.role === "user"
        ? `"${last.content.slice(0, 48)}${last.content.length > 48 ? "…" : ""}"`
        : "the last assistant message";
    if (!(await confirm({ title: `Delete ${label}?`, tone: "alert" }))) return;
    const removed = stream.deleteLastMessage();
    if (removed) {
      toast.success("Message deleted", {
        action: {
          label: "UNDO",
          onClick: () => stream.restoreMessage(removed),
        },
      });
    }
  };

  const handleClearSession = async () => {
    if (stream.messages.length === 0) {
      toast.info("Session is already empty.");
      return;
    }
    if (
      !(await confirm({
        title: "Clear all messages?",
        detail: "This removes the entire conversation from this session.",
        confirmLabel: "CLEAR",
        tone: "alert",
      }))
    )
      return;
    const snapshot = stream.clearMessages();
    toast.success("Session cleared", {
      action: {
        label: "UNDO",
        onClick: () => stream.restoreMessages(snapshot),
      },
    });
  };

  return (
    <div class="flex h-full min-h-0 gap-4">
      {/* Session list — desktop sidebar */}
      <aside class="hidden w-56 shrink-0 lg:block">
        <Panel label="SESSIONS" flush>
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
              <Text variant="readout" tone="bright">
                {headerTitle()}
              </Text>
              <span class="flex items-center gap-1.5">
                <StatusFlag status="nominal">{headerModel()}</StatusFlag>
                <InfoHint
                  label={`Answers in this conversation are generated by ${headerModel()}. Switch models in Settings.`}
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
            >
              {stream.sending() ? "STREAMING" : "IDLE"}
            </StatusFlag>
            <Button variant="ghost" leading="plus" onClick={startNew}>
              NEW
            </Button>
            <Menu
              trigger={
                <Button variant="ghost" aria-label="Session actions">
                  ···
                </Button>
              }
              items={
                [
                  {
                    label: "DELETE LAST MESSAGE",
                    icon: "trash",
                    danger: true,
                    disabled: stream.messages.length === 0 || stream.sending(),
                    onSelect: handleDeleteLast,
                  },
                  {
                    label: "CLEAR SESSION",
                    icon: "close",
                    danger: true,
                    disabled: stream.messages.length === 0 || stream.sending(),
                    onSelect: handleClearSession,
                  },
                ] satisfies MenuItem[]
              }
            />
          </div>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto py-2">
          <Show
            when={stream.messages.length}
            fallback={
              <EmptyState
                icon="terminal"
                message="START A CONVERSATION"
                hint={`${headerModel()} is loaded and ready. Ask a question, request a summary, or describe a task to begin.`}
              />
            }
          >
            <For each={stream.messages}>
              {(message) => <MessageItem message={message} />}
            </For>
          </Show>
        </div>

        <div class="sticky bottom-0 -mx-1">
          <Composer
            disabled={stream.sending()}
            onSend={stream.send}
            storageKey={composerKey()}
          />
        </div>
      </section>
    </div>
  );
}
