import { For, Show, createMemo, type JSX } from "solid-js";
import { Button, EmptyState, ErrorBoundary } from "~/ui";
import type { ConversationActions } from "../conversationActions";
import type { createChatStream } from "../stream/chatStream";
import type { TranscriptFollow } from "../transcriptScroll";
import type { ChatViewport } from "../useChatViewport";
import { MessageItem } from "./MessageItem";

export interface TranscriptViewProps {
  stream: ReturnType<typeof createChatStream>;
  viewport: ChatViewport;
  actions: ConversationActions;
  scroll: TranscriptFollow;
  conversationId: () => string | null;
  /** The reading measure, shared with the composer dock so the two agree. */
  measure: string;
}

/**
 * The scrolling conversation, and what each turn's controls are wired to.
 *
 * Every per-turn affordance the operator has — regenerate, edit, fork, rewind, pin,
 * withdraw a queued message, reattach a dropped run — resolves here, against the stream
 * for anything about a run and against the thread actions for anything about the
 * conversation. The room around it owns none of that; it owns where this sits.
 */
export function TranscriptView(props: TranscriptViewProps): JSX.Element {
  // Everything before the newest compaction divider is still in the transcript but
  // out of what the model replays. The transcript is the only place that knows a
  // turn's position relative to the fold, so the dim pass is derived here —
  // presentation only; the backend decided what it folded.
  const foldedThrough = createMemo(() => {
    let last = -1;
    props.stream.messages.forEach((m, i) => {
      if (m.role === "compaction") last = i;
    });
    return last;
  });

  return (
    <div class="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={props.scroll.ref}
        tabindex={-1}
        onScroll={props.scroll.onScroll}
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
        <div class={props.measure}>
          {/* One malformed block must not cost the operator the composer,
              the thread list, or the text they were typing — scope a throw
              in the message tree to the scroll region. Switching threads
              resets it. */}
          <ErrorBoundary
            message="This conversation failed to render"
            resetKey={props.conversationId}
          >
            <Show
              when={props.stream.messages.length}
              fallback={
                <EmptyState
                  icon="chat"
                  message="Start a conversation"
                  hint="Ask a question, request a summary, or describe a task to begin."
                />
              }
            >
              <For each={props.stream.messages}>
                {(message, index) => (
                  <MessageItem
                    message={message}
                    dimmed={index() < foldedThrough()}
                    onResolveApproval={props.stream.resolveApproval}
                    onResolveHostCommands={props.stream.resolveHostCommands}
                    onRegenerate={() =>
                      void props.stream.regenerate(message.id)
                    }
                    onContinue={() =>
                      void props.stream.continueTurn(message.id)
                    }
                    onEditMessage={(id, text) =>
                      void props.stream.edit(id, text)
                    }
                    onSwitchVersion={(id, i) =>
                      void props.stream.switchVersion(id, i)
                    }
                    onTogglePin={() =>
                      void props.stream.toggleMessagePin(message.id)
                    }
                    onWithdraw={() => {
                      if (message.queuedMessageId)
                        void props.stream.withdrawQueued(
                          message.queuedMessageId,
                        );
                    }}
                    onEditQueued={(text) => {
                      if (message.queuedMessageId)
                        void props.stream.editQueued(
                          message.queuedMessageId,
                          text,
                        );
                    }}
                    onOpenInView={props.viewport.openViewTo}
                    viewItems={props.viewport.items}
                    seenKey={() => props.viewport.state().seenKey}
                    onReattach={() => {
                      if (message.runId)
                        void props.stream.reattachRun(message.runId, {
                          fromSeq: props.stream.lastSeq(),
                        });
                    }}
                    onRewind={() => void props.stream.rewind(message.id)}
                    onFork={() => void props.actions.fork(message.id)}
                    onDelete={() =>
                      void props.actions.removeMessage(message.id)
                    }
                  />
                )}
              </For>
            </Show>
          </ErrorBoundary>
        </div>
      </div>
      <Show when={props.scroll.showJump()}>
        <Button
          variant="default"
          size="sm"
          leading="chevron-down"
          onClick={props.scroll.jumpToLatest}
          class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-surface"
        >
          Jump to latest
        </Button>
      </Show>
    </div>
  );
}
