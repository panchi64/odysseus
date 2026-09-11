/**
 * Dragging the viewport's edge, and knowing how much room there is to drag it in.
 *
 * Two small pieces of measurement that the room used to carry inline, and that have nothing
 * to do with what the room renders.
 *
 * **The drag is an override, not a seeded copy.** While a pointer is down the width lives
 * here, in memory, so a drag never writes localStorage on every move; the persisting setter
 * is called once, when the drag settles. Holding it as an *override* (rather than seeding a
 * local copy from the stored value) is what lets the slot go back to following the stored
 * width the instant the drag ends, and what makes "no drag in flight" expressible at all:
 * null means nothing was dragged, so a bare click on the splitter cannot persist a
 * row-clamped reading over a wider stored preference.
 *
 * **A live drag outranks the derived floor.** The open set contributes a minimum width, and
 * that minimum can move mid-gesture when a surface arrives — but re-clamping the pointer's
 * own number against a floor that shifted under it would jump the edge away from the
 * cursor. The drag clamps against the set it started with.
 *
 * **The available width is measured off the row, not the window.** The nav rail and the
 * shell's padding are already spent by the time the layout reaches here, so clamping
 * against the window would reserve a transcript that isn't there and let the aside overflow
 * the shell. A `ResizeObserver` rather than a `resize` listener, since the rail is
 * drag-sizable and the window never fires for that.
 */

import { createSignal, onCleanup } from "solid-js";
import {
  clampWidth,
  panelWidth,
  setAvailableWidth,
  setPanelWidth,
} from "./viewport/viewportWidth";
import type { SurfaceId } from "./viewport/surfaces";

export interface PanelResize {
  /** The width to lay the slot out at: the live drag if one is in flight, else the
   *  stored preference clamped to what is open. */
  liveWidth: () => number;
  /** `onResize` for the splitter — `dx` is the pointer's delta, and the panel sits on
   *  the right, so a rightward drag narrows it. */
  onResize: (dx: number) => void;
  /** `onResizeEnd` for the splitter: persist and drop the override. */
  onResizeEnd: () => void;
}

/** The drag controller for the viewport slot. `open` reports which surfaces are in the
 *  panel now — it is what the width's floor is derived from. */
export function createPanelResize(
  open: () => readonly SurfaceId[],
): PanelResize {
  const [drag, setDrag] = createSignal<{
    open: readonly SurfaceId[];
    width: number;
  } | null>(null);

  return {
    liveWidth: () => drag()?.width ?? panelWidth(open()),
    onResize: (dx: number) => {
      const started = drag();
      const set = started?.open ?? open();
      const from = started?.width ?? panelWidth(set);
      setDrag({ open: set, width: clampWidth(from - dx, set) });
    },
    onResizeEnd: () => {
      const settled = drag();
      if (settled) setPanelWidth(settled.width, settled.open);
      setDrag(null);
    },
  };
}

/** Publish the row's width to the width store and keep it current. Call from `onMount`
 *  with the row element; the seed is synchronous because the panel is laid out from this
 *  number, and starting at "unmeasured" would paint one frame at a width the row cannot
 *  hold. */
export function observeAvailableWidth(row: HTMLElement): void {
  setAvailableWidth(row.clientWidth);
  const observer = new ResizeObserver(([entry]) => {
    setAvailableWidth(entry.contentRect.width);
  });
  observer.observe(row);
  onCleanup(() => observer.disconnect());
}
