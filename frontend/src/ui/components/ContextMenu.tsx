import { createSignal, splitProps, type JSX } from "solid-js";
import { FloatingPanel } from "./Popover";
import { MenuItems, type MenuItem } from "./menuItems";
import { type Rect } from "./popoverPlacement";

/** What the api hands a caller's "···" button: the ARIA a menu trigger owes an
 *  assistive-technology user, plus the click that opens the same menu the right-click
 *  does. Spread it directly (`{...api.triggerProps(row.id)}`) — the values are read
 *  through getters so `aria-expanded` tracks the menu, which it cannot do if the
 *  object is snapshotted into a variable first. */
export interface ContextMenuTriggerProps {
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  onClick: (e: MouseEvent) => void;
}

export interface ContextMenuApi {
  /** Is the menu showing at all. */
  open: () => boolean;
  /** The key passed to whichever call opened it, or null — one menu instance serves a
   *  whole list, and this is how a row knows the open menu is *its* menu. */
  openKey: () => string | null;
  /** `openKey() === key`. What a row holds its hover-revealed trigger visible on: the
   *  pointer has left the row for the panel, so `group-hover` alone drops the "···"
   *  out from under the menu it opened. */
  isOpen: (key: string) => boolean;
  /** Right-click entry point. Suppresses the browser's own menu and anchors at the
   *  cursor. Pass the row's key so the panel and the row agree on who is open. */
  openAt: (e: MouseEvent, key?: string) => void;
  /** Button entry point — anchors under the element the way `Menu` does. This is the
   *  keyboard/AT path, since a right-click is reachable by pointer only. */
  openAtElement: (el: HTMLElement, key?: string) => void;
  close: () => void;
  /** ARIA + click wiring for that button, so no caller has to restate it. */
  triggerProps: (key?: string) => ContextMenuTriggerProps;
  /** What `ContextMenu` places itself against. Not for callers. */
  anchor: () => Rect | null;
  /** Alignment of the current anchor. Not for callers. */
  align: () => "left" | "right";
}

export interface ContextMenuProps {
  api: ContextMenuApi;
  /** Re-supplied by the caller for whichever row opened the menu — one panel, many
   *  rows, so the items are a function of the open row rather than a fixed list. */
  items: () => MenuItem[];
}

/** A cursor point as a degenerate anchor rect. The placement rules already flip a
 *  panel above an anchor that is too near the bottom and clamp it inside the right
 *  edge; a zero-size rect gets both of those for a point, with no geometry of its own
 *  to keep in step with the popovers'. */
function pointRect(x: number, y: number): Rect {
  return { top: y, bottom: y, left: x, right: x, width: 0, height: 0 };
}

/** Where the open menu is anchored, and how it hangs off that anchor. Bundled because
 *  the two are decided together: a cursor menu opens rightward from the point, while a
 *  menu dropped from a "···" button is right-aligned under it like `Menu`'s. */
interface Anchor {
  rect: () => Rect;
  align: "left" | "right";
}

/** State for a `ContextMenu`. One instance serves an entire list: a row hands it its
 *  own items when it opens it, so a hundred rows cost one panel, one Escape listener
 *  and one backdrop rather than a hundred.
 *
 *  Open state *is* the anchor — there is no second boolean to fall out of sync with
 *  it, and no way to be open with nowhere to be. */
export function createContextMenu(): ContextMenuApi {
  const [anchor, setAnchor] = createSignal<Anchor | null>(null);
  const [openKey, setOpenKey] = createSignal<string | null>(null);

  const open = () => anchor() !== null;
  const close = () => {
    setAnchor(null);
    setOpenKey(null);
  };

  const openAt = (e: MouseEvent, key?: string): void => {
    e.preventDefault();
    // The rect is frozen at the point the operator clicked, unlike the element case
    // below: a cursor menu belongs where the cursor was, and chasing a scroll would
    // slide it away from the thing it was aimed at.
    const rect = pointRect(e.clientX, e.clientY);
    setAnchor({ rect: () => rect, align: "left" });
    setOpenKey(key ?? null);
  };

  const openAtElement = (el: HTMLElement, key?: string): void => {
    // Re-read per placement pass so the panel stays pinned to the button through a
    // scroll of the list underneath it — but **only while that button is still in the
    // document**, and the last good rect stands once it isn't.
    //
    // Without the guard the menu teleports. A list that refetches under an open menu
    // (the rail polls every few seconds while any thread is running) hands `<For>` new
    // item references, which rebuilds every row; the element captured here is then
    // detached, `getBoundingClientRect` on a detached node is all zeros, and the panel
    // relocates to the top-left corner of the window. Freezing beats chasing: the
    // replacement row is in the same place the old one was, so the stale rect is
    // still the right answer.
    let last = el.getBoundingClientRect();
    setAnchor({
      rect: () => {
        if (el.isConnected) last = el.getBoundingClientRect();
        return last;
      },
      align: "right",
    });
    setOpenKey(key ?? null);
  };

  const isOpen = (key: string) => openKey() === key;

  return {
    open,
    openKey,
    isOpen,
    openAt,
    openAtElement,
    close,
    anchor: () => anchor()?.rect() ?? null,
    align: () => anchor()?.align ?? "left",
    triggerProps: (key?: string) => ({
      "aria-haspopup": "menu",
      get "aria-expanded"() {
        return key === undefined ? open() : isOpen(key);
      },
      onClick: (e: MouseEvent) => {
        // The row underneath is usually clickable itself; opening its overflow menu
        // must not also navigate into it.
        e.stopPropagation();
        openAtElement(e.currentTarget as HTMLElement, key);
      },
    }),
  };
}

/** The panel half. Renders nothing where it sits — the menu is portalled — so it can
 *  live anywhere in the list's markup. Inherits the shared panel's rise, elevation and
 *  radius, and its `role="menu"` rows, from `FloatingPanel` and `MenuItems`. */
export function ContextMenu(props: ContextMenuProps): JSX.Element {
  const [local] = splitProps(props, ["api", "items"]);
  return (
    <FloatingPanel
      open={() => local.api.open()}
      onClose={() => local.api.close()}
      anchor={() => local.api.anchor()}
      align={local.api.align()}
      panelClass="min-w-40 py-1"
      // A right-click while the menu is up lands on the backdrop, not on the row the
      // operator aimed at. Closing (and swallowing the native menu) at least leaves
      // the next right-click free to reach that row.
      onBackdropContextMenu={(e) => {
        e.preventDefault();
        local.api.close();
      }}
      panel={() => (
        <MenuItems items={local.items()} close={() => local.api.close()} />
      )}
    />
  );
}
