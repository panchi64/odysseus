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
  // On by default: an unwrapped split diff puts the whole file behind a
  // horizontal scroll and lets long lines run across the column divider.
  softWrap: true,
  fullscreen: false,
  seenKey: null,
};

const V3_KEY = "ody.chat.viewer.v3";
/** Prior per-conversation record — identical in shape, but written when `softWrap`
 *  defaulted *off*. Left in place, read once to seed a conversation's first v3
 *  entry: every other preference carries over, only `softWrap` is re-defaulted,
 *  so an existing thread picks up the new resting state without losing its
 *  open/pin/tab/font/seen position. */
const V2_KEY = "ody.chat.viewer.v2";
/** Legacy per-conversation open-state map (`ChatRoomScreen`'s prior `VIEWPORT_KEY`).
 *  Left in place on migration — only read once, to seed a conversation that has
 *  no v3 *or* v2 entry. */
const LEGACY_OPEN_KEY = "ody.chat.viewport";
/** Legacy (and still current) global panel width key — `panelWidth` keeps using it
 *  directly rather than folding width into the per-conversation v2 record. */
const WIDTH_KEY = "ody.chat.viewport.w";
const SCROLL_KEY = "ody.chat.viewer.scroll";
const SCROLL_LRU_CAP = 200;

const WIDTH_DEFAULT = 384;
const WIDTH_MIN = 320;
/** The widest the panel may be asked for. The *effective* max is also bounded by the
 *  window (see `ceiling`), so this is a preference cap rather than a layout one. */
const WIDTH_CEILING = 1200;
/** Room the conversation column keeps however wide the panel is dragged — below this
 *  the transcript stops being a transcript and becomes a gutter. */
const TRANSCRIPT_MIN = 480;

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

function readV3Map(): PersistedMap {
  return readJson<PersistedMap>(V3_KEY) ?? {};
}

function writeV3Map(map: PersistedMap): void {
  writeLS(V3_KEY, JSON.stringify(map));
}

function readV2Map(): PersistedMap {
  return readJson<PersistedMap>(V2_KEY) ?? {};
}

function readLegacyOpenMap(): Record<string, boolean> {
  return readJson<Record<string, boolean>>(LEGACY_OPEN_KEY) ?? {};
}

/** A conversation's v3 entry, seeded the first time it's read: from its v2 record
 *  when there is one (everything but `softWrap`, which takes the new default),
 *  else from the legacy open-state map. Neither older key is written again. */
function seedState(
  conversationId: string,
  map: PersistedMap,
): ViewerPersistedState {
  const existing = map[conversationId];
  if (existing) return existing;
  const prior = readV2Map()[conversationId];
  if (prior)
    return { ...DEFAULT_STATE, ...prior, softWrap: DEFAULT_STATE.softWrap };
  const legacyOpen = readLegacyOpenMap()[conversationId] ?? false;
  return { ...DEFAULT_STATE, open: legacyOpen };
}

// Module-level so the panel's state survives the screen remounting on navigation —
// same rationale as `claimAutoOpen` below in `viewport.ts`.
const [v3Map, setV3Map] = createSignal<PersistedMap>(readV3Map());

/** Per-conversation View panel state, backed by localStorage. `state()` is reactive
 *  (tracks the module-level store); `patch` merges and persists immediately. */
export function useViewerPersistence(conversationId: () => string): {
  state: () => ViewerPersistedState;
  patch: (p: Partial<ViewerPersistedState>) => void;
} {
  const state = (): ViewerPersistedState =>
    seedState(conversationId(), v3Map());
  const patch = (p: Partial<ViewerPersistedState>): void => {
    const id = conversationId();
    const next: ViewerPersistedState = { ...seedState(id, v3Map()), ...p };
    const nextMap = { ...v3Map(), [id]: next };
    setV3Map(nextMap);
    writeV3Map(nextMap);
  };
  return { state, patch };
}

/** How much width the panel's row actually has, reactively — set by the screen that
 *  owns the row (`ChatRoomScreen`, from a `ResizeObserver` on it).
 *
 *  It has to be the **row**, not the window: by the time the layout reaches here the
 *  nav rail and the shell's padding are already spent, so clamping against
 *  `window.innerWidth` reserves a transcript that isn't there and lets the panel take
 *  ~300px more than the row can give — the conversation column is then squeezed past
 *  its min-content and the row overflows the shell. `Infinity` until the first
 *  measurement, so the ceiling stands alone rather than guessing at a box nobody has
 *  measured yet. */
const [availableWidth, setAvailableWidth] = createSignal(Infinity);

export { setAvailableWidth };

/** The widest the panel may be right now: its own ceiling, less what the row cannot
 *  spare. */
function ceiling(): number {
  return Math.max(
    WIDTH_MIN,
    Math.min(WIDTH_CEILING, availableWidth() - TRANSCRIPT_MIN),
  );
}

/** Clamps a candidate panel width to the draggable range — exported so a live drag
 *  (see `panelResize.ts`) can apply the same bounds per pointermove tick without
 *  persisting until the drag settles.
 *
 *  Floor and ceiling cannot fight: `ceiling()` is itself floored at `WIDTH_MIN`, so on a
 *  row too narrow to spare even that, the panel keeps its minimum and the transcript
 *  takes the squeeze — a panel clamped below the point of legibility would be a worse
 *  answer than a short transcript column. */
export const clampWidth = (w: number): number =>
  Math.min(ceiling(), Math.max(WIDTH_MIN, w));

/** The stored *preference*, unclamped — clamping happens on read (`panelWidth`) so a
 *  width set on a wide display isn't permanently trimmed by one narrow session. */
const [viewWidth, setViewWidth] = createSignal(
  Number(readLS(WIDTH_KEY)) || WIDTH_DEFAULT,
);

/** The panel's global (cross-thread) width. */
export function panelWidth(): number {
  return clampWidth(viewWidth());
}

export function setPanelWidth(w: number): void {
  const clamped = clampWidth(w);
  setViewWidth(clamped);
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

// The approval deep-link's "scroll the card into view and flash it" intent lived here.
// It has no work left to do: a park now takes over the composer's slot, so it is on
// screen the moment the thread opens — there is nothing to scroll to, and the panel's
// own arrival is the emphasis the flash used to supply.
//
// The panel's download seam lived here too, as a single unowned signal. It moved to
// `downloadRegistry.ts` when it grew owners — see that module for why a claim now
// belongs to the component that made it.
