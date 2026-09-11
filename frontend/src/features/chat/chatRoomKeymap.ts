/**
 * The chat room's keyboard bindings.
 *
 * Almost all of them are the viewport's, and they are panel-scoped: the single-letter
 * combos fire only while focus is inside the panel, so the transcript and the composer
 * keep every unmodified key for typing. The two jump targets — the panel and the
 * transcript's scroll container — are what `mod+shift+u` swings between.
 *
 * **Some are the panel's and some are one surface's.** Paging versions and flipping
 * PREVIEW/CODE belong to the View, and they gate on the View being the *focused*
 * surface rather than merely on the panel having focus — with two panes open, `[`
 * pressed while working in a diff should not page the versions of a view the operator
 * is not looking at. Closing a pane, full screen and the digits are the panel's own and
 * gate on panel focus alone.
 *
 * **Esc is shared, so it is yielded rather than claimed.** Any *other* portal-rendered
 * dialog (the rename modal, an attachment lightbox) already handles it, and two handlers
 * on one key means an Esc that closes two things at once. The sheet marks itself
 * `data-view-sheet` so it is not counted as one of those others.
 */

import { registerKeymap, type KeyBinding } from "~/lib/keymap";
import { triggerDownload } from "./viewport/downloadRegistry";
import { SURFACE_IDS } from "./viewport/surfaces";
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

  /** While the panel has focus at all. */
  const inPanel = viewport.hasFocus;
  /** While the View in particular is the pane being worked in. */
  const inView = () =>
    viewport.hasFocus() && viewport.focusedSurface() === "view";

  /** `1`…`n` toggle the nth surface *that has anything to show*, in registry order —
   *  so the digits track what the header row offers rather than the full registry,
   *  and `2` never lands on a surface with nothing behind it. */
  const digitBindings = (): KeyBinding[] =>
    SURFACE_IDS.slice(0, 9).map((_, i) => ({
      combo: String(i + 1),
      when: inPanel,
      run: () => {
        const id = SURFACE_IDS.filter(viewport.available)[i];
        if (id) viewport.toggleSurface(id);
      },
    }));

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
      when: inView,
      run: () =>
        viewport.requestTab(
          viewport.viewState().activeTab === "preview" ? "code" : "preview",
        ),
    },
    { combo: "[", when: inView, run: viewport.pinPrev },
    { combo: "]", when: inView, run: viewport.pinNext },
    {
      combo: "f",
      when: inPanel,
      run: viewport.toggleFullscreen,
    },
    {
      // `shift+w`, not bare `w`: it sits beside `mod+w`, and a mistyped modifier on
      // a close is the one mistype worth making harder.
      combo: "shift+w",
      when: inPanel,
      run: () => {
        const id = viewport.focusedSurface();
        if (id) viewport.closeSurface(id);
      },
    },
    { combo: "d", when: inPanel, run: triggerDownload },
    ...digitBindings(),
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
