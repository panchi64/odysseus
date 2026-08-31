/**
 * The chat room's keyboard bindings.
 *
 * Almost all of them are the viewport's, and they are panel-scoped: the single-letter
 * combos fire only while focus is inside the panel, so the transcript and the composer
 * keep every unmodified key for typing. The two jump targets — the panel and the
 * transcript's scroll container — are what `mod+shift+u` swings between.
 *
 * **Esc is shared, so it is yielded rather than claimed.** Any *other* portal-rendered
 * dialog (the rename modal, an attachment lightbox) already handles it, and two handlers
 * on one key means an Esc that closes two things at once. The sheet marks itself
 * `data-view-sheet` so it is not counted as one of those others.
 */

import { registerKeymap } from "~/lib/keymap";
import type { ChatViewport } from "./useChatViewport";

export interface ChatRoomKeymapDeps {
  viewport: ChatViewport;
  /** Move focus to the transcript's scroll container, if it is mounted. */
  focusTranscript: () => void;
  /** Stage a new conversation — the one binding that is not the viewport's. */
  startNew: () => void;
}

export function registerChatRoomKeymap(deps: ChatRoomKeymapDeps): void {
  const { viewport } = deps;
  const otherDialogOpen = () =>
    document.querySelector(
      '[role="dialog"][aria-modal="true"]:not([data-view-sheet])',
    ) !== null;

  registerKeymap(() => [
    // ⌘/Ctrl+Shift+O starts a new conversation from anywhere, even mid-thread.
    { combo: "mod+shift+o", run: deps.startNew },
    { combo: "mod+shift+v", run: viewport.toggle },
    {
      combo: "mod+shift+u",
      when: () => viewport.shown(),
      run: () => {
        if (viewport.hasFocus()) deps.focusTranscript();
        else viewport.focusPanel();
      },
    },
    {
      combo: "p",
      when: viewport.hasFocus,
      run: () =>
        viewport.requestTab(
          viewport.state().activeTab === "preview" ? "code" : "preview",
        ),
    },
    { combo: "[", when: viewport.hasFocus, run: viewport.pinPrev },
    { combo: "]", when: viewport.hasFocus, run: viewport.pinNext },
    {
      combo: "f",
      when: viewport.hasFocus,
      run: () => viewport.patch({ fullscreen: !viewport.state().fullscreen }),
    },
    {
      combo: "d",
      when: viewport.hasFocus,
      run: viewport.triggerActiveDownload,
    },
    {
      combo: "escape",
      when: () => viewport.hasFocus() && !otherDialogOpen(),
      run: () => {
        if (viewport.sheetOpen()) viewport.closeSheet();
        else deps.focusTranscript();
      },
    },
  ]);
}
