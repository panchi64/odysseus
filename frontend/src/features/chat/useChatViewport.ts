/**
 * The viewport pane, as one thing.
 *
 * The collapsible, resizable region beside the conversation — where documents, live
 * previews and the agent's browser mount — is a single concern with a lot of surface:
 * what it holds, whether it is open, how wide it is, which version is pinned, how many
 * items have arrived unseen, whether it renders as an aside or as a full-screen sheet,
 * and where focus goes when it closes. All of that was inline in the chat screen, where
 * it made up a third of the file and interleaved with the transcript and the composer.
 * None of it is about a conversation; all of it is about a panel.
 *
 * **The dragged width is global; everything else is per conversation.** A manual close
 * on one thread must not be undone by a different thread's auto-open, so `open`, the
 * pinned version, the PREVIEW/CODE tab, the font size, wrap, fullscreen and the
 * seen-through pointer all go through `useViewerPersistence` keyed by thread. The width
 * is a genuine cross-thread preference and is the one thing that does not.
 *
 * Refs are handed back rather than taken: the row the pane shares width with, and the
 * header button focus returns to when a sheet closes, are both rendered by the screen.
 */

import {
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
  type Accessor,
} from "solid-js";
import { createPanelResize, observeAvailableWidth } from "./panelResize";
import type { ChatMessage, ViewSnapshotRef } from "./model";
import {
  activeDownload,
  downloadBlob,
  useViewerPersistence,
  type PanelKind,
  type ViewerPersistedState,
} from "./viewerPersistence";
import { claimAutoOpen, collectViewItems, type ViewItem } from "./viewport";

/** What the pane needs from the room's stream — narrowed to the three reads, so a
 *  panel can be reasoned about without the whole streaming controller. */
export interface ViewportSource {
  messages: ChatMessage[];
  snapshots: Accessor<ViewSnapshotRef[]>;
  browserStream: Accessor<string | null>;
  toggleSnapshotKeeper: (snapshotId: string, keeper: boolean) => Promise<void>;
}

export interface ChatViewport {
  state: () => ViewerPersistedState;
  patch: (next: Partial<ViewerPersistedState>) => void;
  items: Accessor<ViewItem[]>;
  /** Whether there is anything at all to show — the eye toggle's enablement. */
  hasContent: () => boolean;
  /** Rendered as the desktop aside. */
  asideOpen: () => boolean;
  /** Rendered as the full-screen sheet (below `lg`, or in fullscreen at any width). */
  sheetOpen: () => boolean;
  /** Either mount is showing. */
  shown: () => boolean;
  liveWidth: () => number;
  onResize: (dx: number) => void;
  onResizeEnd: () => void;
  /** Items minted after the seen-through pointer — the badge on the eye toggle. */
  unseenCount: () => number;
  toggle: () => void;
  /** Close the sheet: drop fullscreen and give focus back to the trigger. */
  closeSheet: () => void;
  selectView: (key: string) => void;
  openViewTo: (key: string) => void;
  requestTab: (tab: "preview" | "code") => void;
  pinPrev: () => void;
  pinNext: () => void;
  triggerActiveDownload: () => void;
  toggleKeeper: (item: ViewItem) => void;
  /** Whether focus is inside the panel — the gate on its scoped key bindings. */
  hasFocus: () => boolean;
  panelRef: (el: HTMLDivElement) => void;
  focusPanel: () => void;
  /** For the row the conversation and the pane share their width in. */
  rowRef: (el: HTMLDivElement) => void;
  /** For the header control that opens the pane, so closing can restore focus. */
  triggerRef: (el: HTMLButtonElement) => void;
}

export function useChatViewport(
  currentId: () => string | null,
  source: ViewportSource,
): ChatViewport {
  const conversationKey = () => currentId() ?? "new";
  const { state, patch } = useViewerPersistence(conversationKey);

  // The conversation's View, derived from this thread's transcript blocks
  // (presentation-only, so it's automatically thread-scoped).
  const items = createMemo(() =>
    collectViewItems(source.messages, source.snapshots()),
  );
  // The pane only makes sense with something to show. Gating the effective open state
  // on having items keeps a persisted-open thread that has since lost them (or a fresh
  // chat that never had any) from showing an empty panel. The browser is not a View
  // item — no version, no code, no history — so it has to be counted here or the slot
  // would stay shut through a whole browsing session.
  const hasContent = () =>
    items().length > 0 || source.browserStream() !== null;
  const shown = () => state().open && hasContent();
  // Which panel is in the slot — the browser takes it whenever there is a live one. It
  // is what the slot is *sized* by, so it is derived here rather than read off render.
  const panelKind = (): PanelKind =>
    source.browserStream() !== null ? "browser" : "view";
  const toggle = () => patch({ open: !state().open });
  const open = () => {
    if (!state().open) patch({ open: true });
  };

  // The aside's width, and the drag that changes it (see `panelResize.ts` for why the
  // live width is an override rather than a seeded copy, and why the drag remembers
  // which panel it started on).
  const { liveWidth, onResize, onResizeEnd } = createPanelResize(panelKind);

  // The newest version's key. Following it (pinnedKey null) means freshly-minted
  // versions keep advancing the view instead of leaving it stranded on a stale pick.
  const latestViewKey = (): string | null =>
    items().find((i) => i.isLatest)?.key ?? null;
  const resolvedViewKey = (): string | null =>
    state().pinnedKey ?? latestViewKey();
  const requestPin = (key: string | null) => patch({ pinnedKey: key });
  const requestTab = (tab: "preview" | "code") => patch({ activeTab: tab });
  // Pin a version — except picking the current latest clears the pin, so the pane
  // resumes following new versions as the agent mints them.
  const selectView = (key: string) =>
    requestPin(key === latestViewKey() ? null : key);
  const openViewTo = (key: string) => {
    selectView(key);
    open();
  };

  // First-time-only auto-open: when a thread first produces a View item, open the pane
  // once. `claimAutoOpen` is one-shot per conversation, so a later manual close is
  // respected and subsequent items update it silently.
  createEffect(() => {
    const id = currentId();
    if (id !== null && items().length > 0 && claimAutoOpen(id)) open();
  });
  // The browser gets its own one-shot, keyed on the *session* rather than the thread.
  // The conversation-scoped claim is about one artifact accumulating versions, where a
  // manual close means "not this, thanks" for the rest of the thread; a browser session
  // is a different kind of event — it starts hours later, it is a place the agent went
  // rather than a new version of what it was already showing, and a thread that spent
  // its shot on a View item would otherwise browse the whole session behind a closed
  // panel. Re-announcements of the same session share one claim, so a close during a
  // session is still respected until the next one.
  createEffect(() => {
    const path = source.browserStream();
    if (path !== null && claimAutoOpen(`browser:${path}`)) open();
  });

  // Items minted after the "seen through" pointer. Counting from a key's *position* —
  // not a raw count — means a rewind that shrinks the list and a later regrow past the
  // old count can't coincidentally read as "seen"; a dropped key (rewound away)
  // resolves to index -1, i.e. nothing seen.
  const unseenCount = () => {
    const list = items();
    const idx = list.findIndex((i) => i.key === state().seenKey);
    return Math.max(0, list.length - (idx + 1));
  };
  // Cleared whenever the panel is visible and following the latest — a pinned older
  // version leaves later unseen items counted until the operator returns to latest.
  createEffect(() => {
    if (shown() && state().pinnedKey === null) {
      const latest = items().at(-1)?.key ?? null;
      if (latest !== null && state().seenKey !== latest)
        patch({ seenKey: latest });
    }
  });

  // How much width the conversation and the pane have to share — measured off the row
  // itself rather than the window (see `panelResize.ts`).
  let rowEl: HTMLDivElement | undefined;
  onMount(() => {
    if (rowEl) observeAvailableWidth(rowEl);
  });

  // The pane renders in a desktop-only aside above `lg`; below it (or in fullscreen at
  // any width) it renders in a full-screen sheet instead.
  const [isDesktop, setIsDesktop] = createSignal(true);
  onMount(() => {
    const mq = window.matchMedia("(min-width: 64rem)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    onCleanup(() => mq.removeEventListener("change", update));
  });
  const sheetOpen = () => shown() && (state().fullscreen || !isDesktop());
  const asideOpen = () => shown() && !sheetOpen();

  let trigger: HTMLButtonElement | undefined;
  const closeSheet = () => {
    if (isDesktop()) patch({ fullscreen: false });
    else patch({ fullscreen: false, open: false });
    trigger?.focus();
  };

  const [panelEl, setPanelEl] = createSignal<HTMLDivElement>();
  const hasFocus = () => {
    const el = panelEl();
    return el !== undefined && el.contains(document.activeElement);
  };

  const pinPrev = () => {
    const list = items();
    if (list.length === 0) return;
    const idx = list.findIndex((i) => i.key === resolvedViewKey());
    // A missing key (a persisted pin whose version no longer exists) follows latest,
    // same as pinNext's fallback — so "previous" steps back from the newest item
    // instead of jumping to the oldest.
    const effIdx = idx === -1 ? list.length - 1 : idx;
    const target = list[Math.max(0, effIdx - 1)];
    if (target) selectView(target.key);
  };
  const pinNext = () => {
    const list = items();
    if (list.length === 0) return;
    const idx = list.findIndex((i) => i.key === resolvedViewKey());
    if (idx === -1 || idx >= list.length - 1) requestPin(null);
    else selectView(list[idx + 1].key);
  };

  const triggerActiveDownload = () => {
    const d = activeDownload();
    if (!d) return;
    void (async () => downloadBlob(d.name, await d.getBlob()))();
  };

  // Flip the shown snapshot's keeper bookmark. Relays to the backend; the stream store
  // applies the optimistic update and reverts on failure.
  const toggleKeeper = (item: ViewItem) => {
    if (item.snapshot)
      void source.toggleSnapshotKeeper(item.snapshot.snapshotId, !item.keeper);
  };

  return {
    state,
    patch,
    items,
    hasContent,
    asideOpen,
    sheetOpen,
    shown,
    liveWidth,
    onResize,
    onResizeEnd,
    unseenCount,
    toggle,
    closeSheet,
    selectView,
    openViewTo,
    requestTab,
    pinPrev,
    pinNext,
    triggerActiveDownload,
    toggleKeeper,
    hasFocus,
    panelRef: setPanelEl,
    focusPanel: () => panelEl()?.focus(),
    rowRef: (el) => {
      rowEl = el;
    },
    triggerRef: (el) => {
      trigger = el;
    },
  };
}
