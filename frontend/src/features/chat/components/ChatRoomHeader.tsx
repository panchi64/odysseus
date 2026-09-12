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
  /** What this thread is running on, or null when there is nothing to name. */
  model: () => string | null;
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
 * The thread's identity: what it is called, and what it is running on.
 *
 * The model used to be stamped above every assistant turn instead. That wrote the same
 * name down the whole transcript and still left "what is this thread on?" unanswered,
 * because a turn only speaks for itself — so it is asked once, here, where it stays true
 * as the transcript scrolls. Everything else that stood in this row is in the status
 * strip under the composer.
 *
 * **The other end of the row is what the thread can show you**, and that is a different
 * kind of thing from a name: the branch chip reads out what this thread has changed and
 * opens the patch, and beside it there is a button per surface the panel has something
 * to put in. Identity on the left, ways in on the right — so the row reads as one
 * question answered and one set of doors, rather than six controls in a line.
 *
 * **The subtitle spends no colour.** Hierarchy runs size → weight → brightness (§4), and
 * the resting palette is grey (§5) — an accent here would take the one the screen is
 * allowed, for a label that is orientation rather than focus. The separation is made the
 * way the system makes it: `micro` mono against a sans `readout`, which is the two-voice
 * split (§2) doing the work colour would otherwise be asked to do. A model name is
 * emitted by a process, so mono is also simply what it is.
 */
export function ChatRoomHeader(props: ChatRoomHeaderProps): JSX.Element {
  return (
    // Still `items-center`, against the title block as a whole rather than its first
    // line. With the eyebrow present that block is two lines tall, and top-aligning
    // would hang the session controls level with a 10px label, leaving a gap beneath.
    <header class="flex items-center justify-between gap-3 pb-3">
      <span class="flex min-w-0 flex-col">
        {/* WHAT IT RUNS ON, above the name. Reserves no space when there is nothing
            to name — an empty eyebrow would push the title down a line and leave two
            adjacent threads sitting at different heights.

            It reads above while the workspace hint reads below, and the split is what
            each answers. The hint is context for a name the thread does not have yet,
            so it follows the title; the model is true of the whole thread whether or
            not it has been named, so it leads. The two are near-exclusive anyway —
            the hint appears only for a staged worktree thread. */}
        <Show when={props.model()}>
          {(model) => (
            <Text variant="micro" tone="dim" class="truncate">
              {model()}
            </Text>
          )}
        </Show>
        <span class="flex min-w-0 items-center gap-1.5">
          <Show
            when={props.reveal()}
            fallback={
              <Text variant="readout" tone="bright" class="truncate">
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
                // Same clamp as the static branch above. Without it a long
                // auto-generated name overflows the row while it types itself out
                // and then snaps to an ellipsis the moment the reveal hands over.
                class="truncate"
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
