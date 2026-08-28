import { createEffect, createMemo, onCleanup, type JSX } from "solid-js";
import { useLocation, useNavigate } from "@solidjs/router";
import { Button, Text } from "~/ui";
import { mainChat, refreshSessions, useChatSessions } from "../data";
import { SessionList } from "./SessionList";

/** How often to re-read the list while a thread is working. A run in a thread the
 *  operator navigated away from ends server-side with nothing to tell this client,
 *  so the activity edges would otherwise stay lit until the next turn. */
const ACTIVITY_POLL_MS = 3000;

/** RECENTS — the conversation list, hoisted out of the chat page and into the
 *  app's nav rail so the chat body is free for the conversation plus a viewport
 *  pane. It owns its chat-seam wiring (the shared sessions resource + the
 *  persistent room controller), so the app shell only positions it — no chat
 *  state or logic leaks into the shell. Selecting a thread drives the same
 *  `currentId` the room renders; opening from off the chat route navigates there
 *  first. */
export function RecentsRail(): JSX.Element {
  const sessions = useChatSessions();
  const { currentId, setCurrentId } = mainChat();
  const location = useLocation();
  const navigate = useNavigate();

  // Poll only while something is actually running — an idle rail makes no
  // requests, and the poll stops on its own once the last edge clears. Gated on a
  // memoized boolean, not the list itself, so a refetch that changes nothing about
  // activity doesn't tear the timer down and rebuild it.
  const anyActive = createMemo(
    () => sessions()?.some((s) => s.activity) ?? false,
  );
  createEffect(() => {
    if (!anyActive()) return;
    const timer = setInterval(refreshSessions, ACTIVITY_POLL_MS);
    onCleanup(() => clearInterval(timer));
  });

  const toChat = () => {
    if (location.pathname !== "/chat") navigate("/chat");
  };
  const select = (id: string) => {
    setCurrentId(id);
    toChat();
  };
  const startNew = () => {
    setCurrentId(null);
    toChat();
  };

  return (
    <div class="mb-2">
      <div class="flex items-center justify-between px-3 py-1">
        <Text variant="label" tone="dim">
          Recents
        </Text>
        <Button variant="ghost" size="sm" leading="plus" onClick={startNew}>
          New
        </Button>
      </div>
      {/* Cap the height so a long history scrolls within Recents instead of
          pushing the rest of the nav off-screen.

          No rule above the list (§7): a hairline here sat directly on top of the
          first row and read as a border belonging to *that item* rather than as
          a divider under the header. The header's own spacing separates them. */}
      <div class="scrollbar-thin max-h-80 overflow-y-auto">
        <SessionList
          sessions={sessions}
          currentId={currentId()}
          onSelect={select}
        />
      </div>
    </div>
  );
}
