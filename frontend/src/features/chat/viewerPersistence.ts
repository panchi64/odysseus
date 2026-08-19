/** The View panel's own persisted state — presentation-only localStorage seams the
 *  panel and its controls read/write. Nothing here is authoritative: it's the
 *  operator's last-seen UI preference (open/pinned/tab/font/wrap/fullscreen/seen
 *  count), never a business decision. Mirrors the guarded-storage pattern
 *  `~/lib/storage` already centralizes, and the module-level-signal pattern
 *  `viewport.ts`'s `claimAutoOpen` established for the one app-wide panel
 *  instance. */

import { createSignal, onCleanup, onMount } from "solid-js";
import { readLS, writeLS } from "~/lib/storage";

/** Per-conversation View panel preferences. */
export interface ViewerPersistedState {
  open: boolean;
  /** null = follow the newest item; otherwise the pinned item's key. */
  pinnedKey: string | null;
  activeTab: "preview" | "code";
  /** -2..+2, 0 = default size. */
  fontStep: number;
  softWrap: boolean;
  fullscreen: boolean;
  /** The key of the newest View item the operator has seen, or null when none
   *  has. The header badge counts items after this key's position in the
   *  current (chronological) `viewItems()` list — a "seen through" pointer
   *  rather than a raw count, so it self-corrects when the list shrinks (a
   *  rewind/delete) and later regrows past a stale count. A key no longer
   *  present in the list (dropped by a rewind) resolves to "nothing seen". */
  seenKey: string | null;
}

const DEFAULT_STATE: ViewerPersistedState = {
  open: false,
  pinnedKey: null,
  activeTab: "preview",
  fontStep: 0,
  softWrap: false,
  fullscreen: false,
  seenKey: null,
};

const V2_KEY = "ody.chat.viewer.v2";
/** Legacy per-conversation open-state map (`ChatRoomScreen`'s prior `VIEWPORT_KEY`).
 *  Left in place on migration — only read once, to seed a conversation's first v2
 *  entry. */
const LEGACY_OPEN_KEY = "ody.chat.viewport";
/** Legacy (and still current) global panel width key — `viewerWidth` keeps using it
 *  directly rather than folding width into the per-conversation v2 record. */
const WIDTH_KEY = "ody.chat.viewport.w";
const SCROLL_KEY = "ody.chat.viewer.scroll";
const SCROLL_LRU_CAP = 200;

const WIDTH_DEFAULT = 384;
const WIDTH_MIN = 320;
const WIDTH_MAX = 760;

type PersistedMap = Record<string, ViewerPersistedState>;

function readJson<T>(key: string): T | null {
  const raw = readLS(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function readV2Map(): PersistedMap {
  return readJson<PersistedMap>(V2_KEY) ?? {};
}

function writeV2Map(map: PersistedMap): void {
  writeLS(V2_KEY, JSON.stringify(map));
}

function readLegacyOpenMap(): Record<string, boolean> {
  return readJson<Record<string, boolean>>(LEGACY_OPEN_KEY) ?? {};
}

/** A conversation's v2 entry, seeded from the legacy open-state map the first time
 *  it's read (the legacy key is left in place, never written to again). */
function seedState(
  conversationId: string,
  map: PersistedMap,
): ViewerPersistedState {
  const existing = map[conversationId];
  if (existing) return existing;
  const legacyOpen = readLegacyOpenMap()[conversationId] ?? false;
  return { ...DEFAULT_STATE, open: legacyOpen };
}

// Module-level so the panel's state survives the screen remounting on navigation —
// same rationale as `claimAutoOpen` below in `viewport.ts`.
const [v2Map, setV2Map] = createSignal<PersistedMap>(readV2Map());

/** Per-conversation View panel state, backed by localStorage. `state()` is reactive
 *  (tracks the module-level store); `patch` merges and persists immediately. */
export function useViewerPersistence(conversationId: () => string): {
  state: () => ViewerPersistedState;
  patch: (p: Partial<ViewerPersistedState>) => void;
} {
  const state = (): ViewerPersistedState =>
    seedState(conversationId(), v2Map());
  const patch = (p: Partial<ViewerPersistedState>): void => {
    const id = conversationId();
    const next: ViewerPersistedState = { ...seedState(id, v2Map()), ...p };
    const nextMap = { ...v2Map(), [id]: next };
    setV2Map(nextMap);
    writeV2Map(nextMap);
  };
  return { state, patch };
}

/** Clamps a candidate panel width to the draggable range — exported so a live
 *  drag (e.g. `ChatRoomScreen`'s in-memory width signal) can apply the same
 *  bounds per pointermove tick without persisting until the drag settles. */
export const clampWidth = (w: number): number =>
  Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, w));

const [widthSignal, setWidthSignal] = createSignal(
  clampWidth(Number(readLS(WIDTH_KEY)) || WIDTH_DEFAULT),
);

/** The global (cross-thread) panel width — same storage key/semantics as the
 *  legacy `ody.chat.viewport.w`. */
export function viewerWidth(): number {
  return widthSignal();
}

export function setViewerWidth(w: number): void {
  const clamped = clampWidth(w);
  setWidthSignal(clamped);
  writeLS(WIDTH_KEY, String(clamped));
}

function readScrollMap(): Record<string, number> {
  return readJson<Record<string, number>>(SCROLL_KEY) ?? {};
}

/** Insert/refresh `key` as the most-recently-used entry, evicting the oldest when
 *  over the cap. Plain-object key order is insertion order, so a delete+re-add
 *  moves `key` to the end and the first remaining key is genuinely the oldest. */
function touchScrollEntry(
  map: Record<string, number>,
  key: string,
  value: number,
): Record<string, number> {
  const next = { ...map };
  delete next[key];
  next[key] = value;
  const keys = Object.keys(next);
  if (keys.length > SCROLL_LRU_CAP) delete next[keys[0]];
  return next;
}

/** Restores `el.scrollTop` for `key()` after mount (next frame), then persists it
 *  debounced ~150ms on scroll, LRU-capped at 200 entries. Call from within a
 *  component's setup (uses `onMount`/`onCleanup` on the calling owner). */
export function rememberScroll(el: HTMLElement, key: () => string): void {
  let saveTimer: ReturnType<typeof setTimeout> | undefined;

  const onScroll = () => {
    if (saveTimer !== undefined) clearTimeout(saveTimer);
    const k = key();
    const y = el.scrollTop;
    saveTimer = setTimeout(() => {
      writeLS(
        SCROLL_KEY,
        JSON.stringify(touchScrollEntry(readScrollMap(), k, y)),
      );
    }, 150);
  };

  onMount(() => {
    requestAnimationFrame(() => {
      const y = readScrollMap()[key()];
      if (typeof y === "number") el.scrollTop = y;
    });
    el.addEventListener("scroll", onScroll, { passive: true });
  });

  onCleanup(() => {
    if (saveTimer !== undefined) clearTimeout(saveTimer);
    el.removeEventListener("scroll", onScroll);
  });
}

// ── Cross-component seams ────────────────────────────────────────────────────
// Single panel instance exists app-wide, so module-level signals are the correct
// scope (mirrors `claimAutoOpen` in `viewport.ts`).

const [dirtyKeySignal, setDirtyKeySignal] = createSignal<string | null>(null);

/** The key of the view item with unsaved edits, or null. */
export function setViewerDirty(key: string | null): void {
  setDirtyKeySignal(key);
}
export function viewerDirty(): string | null {
  return dirtyKeySignal();
}

/** Pending scroll-to-first-change requests, keyed by item — consumed exactly once
 *  each. A plain module-level Set (non-reactive intent, not render state), like
 *  `claimAutoOpen`'s `autoOpened`. */
const pendingAnchors = new Set<string>();

export function requestAnchor(itemKey: string): void {
  pendingAnchors.add(itemKey);
}

/** True exactly once per `requestAnchor` call for this key. */
export function consumeAnchor(itemKey: string): boolean {
  if (!pendingAnchors.has(itemKey)) return false;
  pendingAnchors.delete(itemKey);
  return true;
}

/** How long a "you came for this" highlight lingers before it hard-cuts off (no
 *  fade — design §8). Shared by the document passage-anchor and the approval
 *  deep-link focus so both read as the same mechanical emphasis. */
export const HIGHLIGHT_MS = 2000;

/** A pending "focus the approval card" intent, set when an `approval_needed`
 *  notification is opened and consumed exactly once by the pending (non-stale)
 *  `ApprovalCard` that mounts for that conversation. A plain module-level flag —
 *  non-reactive intent, not render state — like `pendingAnchors` above. */
let approvalFocusPending = false;

export function requestApprovalFocus(): void {
  approvalFocusPending = true;
}

/** True exactly once per `requestApprovalFocus` call. */
export function consumeApprovalFocus(): boolean {
  if (!approvalFocusPending) return false;
  approvalFocusPending = false;
  return true;
}

export interface ActiveDownload {
  name: string;
  getBlob: () => Promise<Blob>;
}

const [downloadSignal, setDownloadSignal] = createSignal<ActiveDownload | null>(
  null,
);

export function setActiveDownload(d: ActiveDownload | null): void {
  setDownloadSignal(d);
}
export function activeDownload(): ActiveDownload | null {
  return downloadSignal();
}

/** Triggers a browser download of `blob` as `name` via a throwaway anchor +
 *  object URL. */
export function downloadBlob(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
