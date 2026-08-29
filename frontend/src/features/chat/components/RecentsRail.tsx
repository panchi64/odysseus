import { createEffect, createMemo, onCleanup, type JSX } from "solid-js";
import { useLocation, useNavigate } from "@solidjs/router";
import { Button, Text } from "~/ui";
import { mainChat, refreshSessions, useChatSessions } from "../data";
import type { ChatActivity } from "../model";
import { SessionList } from "./SessionList";

/** How often to re-read the list while a thread is working. A run in a thread the
 *  operator navigated away from ends server-side with nothing to tell this client,
 *  so the activity edges would otherwise stay lit until the next turn. */
const ACTIVITY_POLL_MS = 3000;

/** RECENTS — the conversation list, and the body of the nav rail itself. It was
 *  hoisted out of the chat page so the chat body is free for the conversation
 *  plus a viewport pane, and it is now what the rail *is*: mounted on every
 *  route, not only `/chat`, because threads are the work and everything that was
 *  configuration went to the settings dialog. It owns its chat-seam wiring (the shared sessions resource + the
 *  persistent room controller), so the app shell only positions it — no chat
 *  state or logic leaks into the shell. Selecting a thread drives the same
 *  `currentId` the room renders; opening from off the chat route navigates there
 *  first. */
export function RecentsRail(): JSX.Element {
  const sessions = useChatSessions();
  const { currentId, setCurrentId, stream } = mainChat();
  const location = useLocation();
  const navigate = useNavigate();

  /** The rows to render: the server's list, plus an echo of the run this client
   *  is already streaming.
   *
   *  Activity is server-derived, and the refresh that fires when a turn starts
   *  races the backend recording the run — so the read comes back saying nothing
   *  is active. That alone would be a brief miss, except the poll below is gated
   *  on the list showing activity, so nothing was left to discover it: the row
   *  stayed dark for the whole run and only lit after a reload. A list that has
   *  to already know something is running in order to find out that something is
   *  running can never light the first one.
   *
   *  So echo what this client plainly knows about its own stream. This is a
   *  presentation echo, not a decision — the next poll replaces it with the
   *  server's answer, and a run started on another device still arrives the
   *  normal way. */
  const rows = createMemo(() => {
    const list = sessions();
    const id = currentId();
    if (!list || !id || !stream.sending()) return list;
    const echo: ChatActivity = stream.awaitingApproval()
      ? "awaiting_input"
      : "running";
    return list.map((s) =>
      s.id === id && !s.activity ? { ...s, activity: echo } : s,
    );
  });

  // Poll only while something is actually running — an idle rail makes no
  // requests, and the poll stops on its own once the last edge clears. Read off
  // `rows`, so the echo above opens the gate too: that is what lets the poll
  // correct and then clear the row it lit optimistically.
  const anyActive = createMemo(() => rows()?.some((s) => s.activity) ?? false);
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
    <div class="flex min-h-0 flex-1 flex-col pb-2">
      <div class="flex items-center justify-between px-3 py-1">
        <Text variant="label" tone="dim">
          Recents
        </Text>
        <Button variant="ghost" size="sm" leading="plus" onClick={startNew}>
          New
        </Button>
      </div>
      {/* The list takes whatever height is left rather than a fixed cap. The cap
          was right when six area sections sat beneath it and a long history would
          have pushed them off-screen; the rail is the thread list now, so a cap
          would leave dead space under it instead.

          No rule above the list (§7): a hairline here sat directly on top of the
          first row and read as a border belonging to *that item* rather than as
          a divider under the header. The header's own spacing separates them. */}
      <div class="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        <SessionList
          sessions={rows}
          currentId={currentId()}
          onSelect={select}
        />
      </div>
    </div>
  );
}
