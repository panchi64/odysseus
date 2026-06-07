import { For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  ListRow,
  LoadingText,
  Panel,
  StatusFlag,
  Text,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useChatSession, useChatSessions, createChatStream } from "../data";
import { MessageItem } from "../components/MessageItem";
import { Composer } from "../components/Composer";

/** Reference feature screen. Demonstrates the full pattern: data via the
 *  model/mocks/data seam, layout from ~/ui only, and a live streaming region. */
export function ChatRoomScreen(): JSX.Element {
  const sessions = useChatSessions();
  const session = useChatSession(() => "s-014");
  const stream = createChatStream(() => session()?.messages);

  return (
    <div class="flex h-full min-h-0 gap-4">
      {/* Session list */}
      <aside class="hidden w-56 shrink-0 lg:block">
        <Panel label="SESSIONS" flush>
          <Suspense
            fallback={
              <div class="p-3">
                <LoadingText />
              </div>
            }
          >
            <For each={sessions()}>
              {(s) => (
                <ListRow
                  label={s.title}
                  selected={s.id === "s-014"}
                  href="/chat"
                  right={
                    <Text variant="micro" tone="dim">
                      {relativeTime(s.updatedAt)}
                    </Text>
                  }
                />
              )}
            </For>
          </Suspense>
        </Panel>
      </aside>

      {/* Conversation */}
      <section class="flex min-h-full min-w-0 flex-1 flex-col">
        <header class="flex items-center justify-between gap-3 border-b border-line pb-3">
          <div class="flex flex-col gap-0.5">
            <Text variant="readout" tone="bright">
              {session()?.title ?? "New session"}
            </Text>
            <Text variant="micro" tone="dim">
              MODEL {session()?.model ?? "—"} · SESSION s-014
            </Text>
          </div>
          <div class="flex items-center gap-2">
            <StatusFlag
              status={stream.sending() ? "info" : "idle"}
              dot={stream.sending()}
            >
              {stream.sending() ? "STREAMING" : "IDLE"}
            </StatusFlag>
            <Button variant="ghost" leading="plus">
              NEW
            </Button>
          </div>
        </header>

        <div class="min-h-0 flex-1 py-2">
          <Show
            when={stream.messages.length}
            fallback={
              <EmptyState
                icon="terminal"
                message="NO MESSAGES"
                hint="Send a message to start the session."
              />
            }
          >
            <For each={stream.messages}>
              {(message) => <MessageItem message={message} />}
            </For>
          </Show>
        </div>

        <div class="sticky bottom-0 -mx-1">
          <Composer disabled={stream.sending()} onSend={stream.send} />
        </div>
      </section>
    </div>
  );
}
