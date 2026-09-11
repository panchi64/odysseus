import { Show, type JSX } from "solid-js";
import {
  Button,
  Frames,
  Icon,
  Menu,
  Text,
  TypewriterText,
  type MenuItem,
} from "~/ui";
import { REVEAL_SPEED_MS } from "../data";
import type { ChatViewport } from "../useChatViewport";
import type { BranchState } from "../data";
import { BranchChip } from "./BranchChip";
import { ViewportSurfaceBar } from "./ViewportSurfaceBar";

/** The session menu's entries — everything that acts on the thread rather than on a
 *  turn in it. Handed in as one object because they arrive as one: they are the
 *  session-actions menu, and splitting them into separate props only spread the same
 *  wiring across as many lines. */
export interface ChatRoomHeaderActions {
  rename: () => void;
  retitle: () => void;
  compact: () => void;
  openBrowser: () => void;
  copy: () => void;
  remove: () => void;
}

export interface ChatRoomHeaderProps {
  title: () => string;
  /** A title the backend has just written, for the typewriter reveal. */
  reveal: () => string | undefined;
  /** The directory a **staged** worktree thread will work in, `parent/name`. Absent for
   *  every saved thread, which names its workspace with the branch chip on the other end
   *  of this row instead — two answers to one question in one row is the thing to avoid.
   *  A staged thread has no branch yet and no row in the rail, so without this the
   *  operator has just clicked `+` on a directory and been shown nothing that names it. */
  workspaceHint: () => string | undefined;
  /** True while the thread is being named — the auto-title or a manual retitle. */
  working: () => boolean;
  conversationId: () => string | null;
  streaming: () => boolean;
  /** Length of the transcript, which is what makes compact and copy available. */
  messageCount: () => number;
  viewport: ChatViewport;
  /** The thread's branch, fetched by the room and shared with the Diff surface. */
  branch: () => BranchState | null | undefined;
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
      <span class="flex min-w-0 flex-col">
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
        {/* Where this thread will work, under the name it does not have yet. Quiet —
            it is context for the title, not a second title. */}
        <Show when={props.workspaceHint()}>
          {(hint) => (
            <span class="flex min-w-0 items-center gap-1.5">
              <Icon name="library" size={12} class="shrink-0 text-dim" />
              <Text variant="micro" tone="dim" class="min-w-0 truncate">
                {hint()}
              </Text>
            </span>
          )}
        </Show>
      </span>
      <div class="flex shrink-0 items-center gap-2">
        {/* A code thread's branch and diffstat, and the way into the patch.
            Renders nothing for a sandbox thread — the backend answers 404 for
            one, which is the ordinary case. */}
        <BranchChip
          branch={props.branch}
          onOpen={() => props.viewport.toggleSurface("diff")}
        />
        {/* One button per surface that has anything to show — the eye toggle
            grown up. It could only ever say "the panel", which was enough while
            the panel held one thing and a guess once it holds several. */}
        <ViewportSurfaceBar viewport={props.viewport} />
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
                label: "Open browser",
                icon: "link",
                // The window belongs to the thread — its cookies and its logins are
                // this conversation's — so there is nothing to open until there is a
                // thread to open it for.
                disabled: !props.conversationId(),
                onSelect: props.actions.openBrowser,
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
