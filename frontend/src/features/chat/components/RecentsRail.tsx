import { type JSX } from "solid-js";
import { useLocation, useNavigate } from "@solidjs/router";
import { Button, Text } from "~/ui";
import { mainChat, useChatSessions } from "../data";
import { SessionList } from "./SessionList";

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
        <Text variant="micro" tone="dim">
          RECENTS
        </Text>
        <Button variant="ghost" size="sm" leading="plus" onClick={startNew}>
          NEW
        </Button>
      </div>
      {/* Cap the height so a long history scrolls within RECENTS instead of
          pushing the rest of the nav off-screen. */}
      <div class="max-h-80 overflow-y-auto border-t border-line">
        <SessionList
          sessions={sessions}
          currentId={currentId()}
          onSelect={select}
        />
      </div>
    </div>
  );
}
