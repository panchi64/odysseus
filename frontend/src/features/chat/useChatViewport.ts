/**
 * The viewport pane, as one thing.
 *
 * The collapsible, resizable region beside the conversation — where documents and live
 * previews mount — is a single concern with a lot of surface: what it holds, whether it
 * is open, how wide it is, which version is pinned, how many items have arrived unseen,
 * whether it renders as an aside or as a full-screen sheet, and where focus goes when it
 * closes. All of that was inline in the chat screen, where it made up a third of the file
 * and interleaved with the transcript and the composer. None of it is about a
 * conversation; all of it is about a panel.
 *
 * **The dragged width is global; everything else is per conversation.** A manual close on
 * one thread must not be undone by a different thread's auto-open, so the layout, the
 * pinned version, the PREVIEW/CODE tab, the font size, wrap, fullscreen and the
 * seen-through pointer all go through `useViewportPersistence` keyed by thread. The width
 * is a genuine cross-thread preference and is the one thing that does not.
 *
 * **What the panel holds is now a layout rather than a flag.** Openness is derived from
 * it — there is no separate `open` to disagree with — and closing keeps the arrangement
 * so reopening restores what the operator was looking at rather than a default. Today
 * that layout only ever holds the View; the machinery underneath it does not care, which
 * is the point.
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
import type { ChatMessage, PermissionLevel, ViewSnapshotRef } from "./model";
import type { BranchState } from "./data";
import type { PlanItem } from "~/lib/stream/events";
import {
  emptyLayout,
  focusInStack,
  hasSurface,
  isEmpty,
  leaf,
  openSurface,
  panelSurfacesOf,
  resizeSplit,
  surfacesOf,
  toggleSurface as toggleLayout,
  type TilingContext,
  type ViewportLayout,
} from "./viewport/layout";
import { panelBox, widenFor } from "./viewport/viewportWidth";
import { createSurfaceSources } from "./viewport/surfaceSources";
import {
  DEFAULT_VIEW_SURFACE,
  useViewportPersistence,
  type ViewportPersistedState,
  type ViewSurfaceState,
} from "./viewport/persistence";
import { SURFACE_IDS, type SurfaceId } from "./viewport/surfaces";
import {
  claimAutoOpen,
  collectViewItems,
  type ViewItem,
} from "./viewport/viewItems";

/** What the pane needs from the room's stream — narrowed to the three reads, so a
 *  panel can be reasoned about without the whole streaming controller. */
export interface ViewportSource {
  messages: ChatMessage[];
  snapshots: Accessor<ViewSnapshotRef[]>;
  plan: Accessor<PlanItem[]>;
  branch: () => BranchState | null | undefined;
  refetchBranch: () => void;
  /** The thread's level — the Plan surface's arrival turns on it — and whether
   *  that level has settled yet. */
  permission: () => PermissionLevel;
  permissionPending: () => boolean;
  toggleSnapshotKeeper: (snapshotId: string, keeper: boolean) => Promise<void>;
}

export interface ChatViewport {
  state: () => ViewportPersistedState;
  patch: (next: Partial<ViewportPersistedState>) => void;
  /** The View surface's own preferences, and the way to change them. Consumers read
   *  these rather than reaching into `state().surfaces`, so where a surface's state
   *  is kept stays this module's business. */
  viewState: () => ViewSurfaceState;
  patchView: (next: Partial<ViewSurfaceState>) => void;
  items: Accessor<ViewItem[]>;
  /** The thread's task list, for the Plan surface. */
  plan: Accessor<PlanItem[]>;
  /** The thread's branch, for the Diff surface. */
  branch: () => BranchState | null | undefined;
  refetchBranch: () => void;
  /** Whether a surface has anything to show — which header buttons exist. */
  available: (id: SurfaceId) => boolean;
  /** Whether a surface is currently in the layout. */
  isOpen: (id: SurfaceId) => boolean;
  /** Bring a surface to the front of the tabbed pane it shares, and focus it. */
  revealSurface: (id: SurfaceId) => void;
  /** Close one surface from its own chrome. */
  closeSurface: (id: SurfaceId) => void;
  /** Drag a split's divider — `path` addresses it, `ratio` is `a`'s share. */
  adjustSplit: (path: readonly ("a" | "b")[], ratio: number) => void;
  /** Which surface the operator is working in. Surface-scoped key bindings gate on
   *  it, and it is what a pane's chrome marks as current. */
  focusedSurface: Accessor<SurfaceId | null>;
  setFocusedSurface: (id: SurfaceId) => void;
  /** Put a surface on screen, or take it off. Closing the last one closes the
   *  panel, since a panel showing nothing is a panel that is shut. */
  toggleSurface: (id: SurfaceId) => void;
  /** Whether there is anything at all to show — the panel's enablement. */
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

/** What an empty panel opens onto when it has no remembered arrangement. */
const DEFAULT_LAYOUT: ViewportLayout = { strips: [], panels: leaf("view") };

export function useChatViewport(
  currentId: () => string | null,
  source: ViewportSource,
): ChatViewport {
  const conversationKey = () => currentId() ?? "new";
  const { state, patch } = useViewportPersistence(conversationKey);

  const viewState = (): ViewSurfaceState =>
    state().surfaces.view ?? DEFAULT_VIEW_SURFACE;
  const patchView = (next: Partial<ViewSurfaceState>): void =>
    patch({
      surfaces: { ...state().surfaces, view: { ...viewState(), ...next } },
    });

  // The conversation's View, derived from this thread's transcript blocks
  // (presentation-only, so it's automatically thread-scoped).
  const items = createMemo(() =>
    collectViewItems(source.messages, source.snapshots()),
  );
  const sources = createSurfaceSources({
    viewItems: items,
    plan: source.plan,
    branch: source.branch,
    permission: source.permission,
    permissionPending: source.permissionPending,
  });
  const available = (id: SurfaceId): boolean => sources[id].available();

  // The pane only makes sense with something to show. Gating the effective open state
  // on that keeps a persisted-open thread that has since lost its content (or a fresh
  // chat that never had any) from showing an empty panel.
  const hasContent = () => SURFACE_IDS.some(available);
  const shown = () => state().layout !== null && hasContent();

  /** Put `id` on screen, remembering the arrangement as the restore point. */
  const show = (id: SurfaceId): void => {
    const current = state().layout ?? emptyLayout();
    if (hasSurface(current, id)) return;
    const next = openSurface(current, id);
    patch({ layout: next, lastLayout: next, focused: id });
  };
  const open = () => {
    if (state().layout !== null) return;
    const restore = state().lastLayout ?? DEFAULT_LAYOUT;
    patch({ layout: restore, focused: surfacesOf(restore)[0] ?? null });
  };
  const close = () => {
    const current = state().layout;
    if (current === null) return;
    patch({ layout: null, lastLayout: current });
  };
  const toggle = () => (state().layout === null ? open() : close());

  /** What the splitting policy divides, and how far it may divide it. Three panes
   *  is generous at full screen and too many beside a transcript, so the cap is the
   *  presentation's rather than a constant. */
  const tiling = (): TilingContext => ({
    box: panelBox(),
    cap: state().fullscreen ? 3 : 2,
  });

  const isOpen = (id: SurfaceId): boolean => {
    const layout = state().layout;
    return layout !== null && hasSurface(layout, id);
  };
  /** A header button's click. Closing the last surface closes the panel rather
   *  than leaving an empty frame behind — "open with nothing in it" is a state
   *  the layout deliberately cannot express. */
  const toggleSurface = (id: SurfaceId): void => {
    const next = toggleLayout(state().layout ?? emptyLayout(), id, tiling());
    if (isEmpty(next)) {
      close();
      return;
    }
    // A surface arriving into a panel too narrow for it widens the panel once. Only
    // on arrival, and only upward: a surface opened and closed repeatedly must not
    // ratchet the panel wider each time.
    widenFor(panelSurfacesOf(next));
    patch({ layout: next, lastLayout: next, focused: id });
  };

  // Which surface the operator is in. Persisted rather than held in a signal of its
  // own: it is part of the arrangement, and a thread returned to should come back
  // with the same pane current as when it was left.
  const focusedSurface = (): SurfaceId | null => state().focused;
  const setFocusedSurface = (id: SurfaceId): void => {
    if (state().focused !== id) patch({ focused: id });
  };

  /** Bring a surface to the front of the stack it shares, and focus it. */
  const revealSurface = (id: SurfaceId): void => {
    const layout = state().layout;
    if (layout === null) return;
    patch({ layout: focusInStack(layout, id), focused: id });
  };

  /** Drag a split's divider. `path` addresses which split; `ratio` is `a`'s share. */
  const adjustSplit = (path: readonly ("a" | "b")[], ratio: number): void => {
    const layout = state().layout;
    if (layout === null) return;
    patch({ layout: resizeSplit(layout, path, ratio) });
  };

  /** Close one surface from its own chrome, rather than from the header. */
  const closeSurface = (id: SurfaceId): void => {
    if (isOpen(id)) toggleSurface(id);
  };

  // The aside's width, and the drag that changes it (see `panelResize.ts` for why the
  // live width is an override rather than a seeded copy).
  const { liveWidth, onResize, onResizeEnd } = createPanelResize(() => {
    const layout = state().layout;
    return layout === null ? [] : panelSurfacesOf(layout);
  });

  // The newest version's key. Following it (pinnedKey null) means freshly-minted
  // versions keep advancing the view instead of leaving it stranded on a stale pick.
  const latestViewKey = (): string | null =>
    items().find((i) => i.isLatest)?.key ?? null;
  const resolvedViewKey = (): string | null =>
    viewState().pinnedKey ?? latestViewKey();
  const requestPin = (key: string | null) => patchView({ pinnedKey: key });
  const requestTab = (tab: "preview" | "code") => patchView({ activeTab: tab });
  // Pin a version — except picking the current latest clears the pin, so the pane
  // resumes following new versions as the agent mints them.
  const selectView = (key: string) =>
    requestPin(key === latestViewKey() ? null : key);
  const openViewTo = (key: string) => {
    selectView(key);
    // `show` opens the panel on its own when the layout is closed — there is no
    // arrangement without one.
    show("view");
  };

  // **Arrival.** A surface that has just gained something may put itself on screen,
  // and whether it may is the surface's own answer rather than a rule the panel
  // applies uniformly — see `surfaceSources.ts`. The claim is one-shot per
  // conversation per surface per *key*, so a manual close is respected, a surface
  // re-rendering does not reopen itself, and a genuinely new arrival (a revised plan
  // still awaiting a yes) earns a fresh one.
  createEffect(() => {
    const conversation = currentId();
    if (conversation === null) return;
    for (const id of SURFACE_IDS) {
      const source = sources[id];
      if (!source.available() || source.arrival() !== "steal") continue;
      if (claimAutoOpen(`${conversation}:${id}:${source.claimKey()}`)) show(id);
    }
  });

  // Items minted after the "seen through" pointer. Counting from a key's *position* —
  // not a raw count — means a rewind that shrinks the list and a later regrow past the
  // old count can't coincidentally read as "seen"; a dropped key (rewound away)
  // resolves to index -1, i.e. nothing seen.
  const unseenCount = () => {
    const list = items();
    const idx = list.findIndex((i) => i.key === state().seen.view);
    return Math.max(0, list.length - (idx + 1));
  };
  // Cleared whenever the panel is visible and following the latest — a pinned older
  // version leaves later unseen items counted until the operator returns to latest.
  createEffect(() => {
    if (shown() && viewState().pinnedKey === null) {
      const latest = items().at(-1)?.key ?? null;
      if (latest !== null && state().seen.view !== latest)
        patch({ seen: { ...state().seen, view: latest } });
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
    // On desktop the sheet is fullscreen, so leaving it drops back to the aside; on a
    // narrow window the sheet *is* the panel, so leaving it closes the panel. One
    // patch either way, since the two settle together.
    const current = state().layout;
    if (isDesktop()) patch({ fullscreen: false });
    else
      patch({
        fullscreen: false,
        layout: null,
        lastLayout: current ?? state().lastLayout,
      });
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

  // Flip the shown snapshot's keeper bookmark. Relays to the backend; the stream store
  // applies the optimistic update and reverts on failure.
  const toggleKeeper = (item: ViewItem) => {
    if (item.snapshot)
      void source.toggleSnapshotKeeper(item.snapshot.snapshotId, !item.keeper);
  };

  return {
    state,
    patch,
    viewState,
    patchView,
    items,
    plan: source.plan,
    branch: source.branch,
    refetchBranch: source.refetchBranch,
    available,
    isOpen,
    toggleSurface,
    revealSurface,
    closeSurface,
    adjustSplit,
    focusedSurface,
    setFocusedSurface,
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
