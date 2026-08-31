import { Show, type JSX } from "solid-js";
import {
  Button,
  Frames,
  Menu,
  Text,
  Tooltip,
  TypewriterText,
  type MenuItem,
} from "~/ui";
import { REVEAL_SPEED_MS } from "../data";
import type { ChatViewport } from "../useChatViewport";
import { BranchChip } from "./BranchChip";

/** The session menu's five entries — everything that acts on the thread rather than
 *  on a turn in it. Handed in as one object because they arrive as one: they are the
 *  session-actions menu, and splitting them into five props only spread the same
 *  wiring across five lines. */
export interface ChatRoomHeaderActions {
  rename: () => void;
  retitle: () => void;
  compact: () => void;
  copy: () => void;
  remove: () => void;
}

export interface ChatRoomHeaderProps {
  title: () => string;
  /** A title the backend has just written, for the typewriter reveal. */
  reveal: () => string | undefined;
  /** True while the thread is being named — the auto-title or a manual retitle. */
  working: () => boolean;
  conversationId: () => string | null;
  streaming: () => boolean;
  /** Length of the transcript, which is what makes compact and copy available. */
  messageCount: () => number;
  viewport: ChatViewport;
  actions: ChatRoomHeaderActions;
}

/**
 * Title only. The model this chat runs on is named on every assistant turn and picked in
 * the app top bar; a third, read-only copy here was the one that read as a control.
 * Everything else that stood in this row is in the status strip under the composer.
 */
export function ChatRoomHeader(props: ChatRoomHeaderProps): JSX.Element {
  return (
    <header class="flex items-center justify-between gap-3 pb-3">
      <span class="flex min-w-0 items-center gap-1.5">
        <Show
          when={props.reveal()}
          fallback={
            <Text variant="readout" tone="bright">
              {props.title()}
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
        <Show when={props.working()}>
          <Frames class="shrink-0 text-info" />
        </Show>
      </span>
      <div class="flex shrink-0 items-center gap-2">
        {/* A code thread's branch and diffstat. Renders nothing for a sandbox
            thread — the backend answers 404 for one, which is the ordinary
            case. Re-reads when a turn settles, since that is when the agent
            has just changed something. */}
        <Show when={props.conversationId()}>
          {(id) => (
            <BranchChip
              conversationId={id()}
              revision={() => (props.streaming() ? 0 : 1)}
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
            ref={props.viewport.triggerRef}
            variant="ghost"
            leading="eye"
            aria-label="Toggle viewport panel"
            onClick={props.viewport.toggle}
            disabled={!props.viewport.hasContent()}
            class={
              props.viewport.hasContent() ? undefined : "hidden lg:inline-flex"
            }
          >
            <Show when={props.viewport.unseenCount() > 0}>
              {props.viewport.unseenCount() > 9
                ? "9+"
                : props.viewport.unseenCount()}
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
                disabled: !props.conversationId(),
                onSelect: props.actions.rename,
              },
              {
                label: "Regenerate title",
                icon: "refresh",
                disabled: !props.conversationId(),
                onSelect: props.actions.retitle,
              },
              {
                label: "Compact now",
                icon: "layers",
                // Nothing to fold in an empty or one-turn thread; the backend
                // refuses those anyway, this just doesn't offer the action.
                disabled: !props.conversationId() || props.messageCount() < 3,
                onSelect: props.actions.compact,
              },
              {
                label: "Copy conversation",
                icon: "copy",
                disabled: props.messageCount() === 0,
                onSelect: props.actions.copy,
              },
              {
                label: "Delete conversation",
                icon: "trash",
                danger: true,
                disabled: !props.conversationId(),
                onSelect: props.actions.remove,
              },
            ] satisfies MenuItem[]
          }
        />
      </div>
    </header>
  );
}
