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
 * width the instant the drag ends — including when the panel swaps under it, so a browser
 * session opening mid-thread re-reads the browser's own width instead of inheriting the
 * width the View was dragged to.
 *
 * **The drag remembers which panel it started on.** Null means no drag happened, so a bare
 * click on the splitter cannot persist a window-clamped reading over a wider stored
 * preference. And a browser session ending mid-drag must not land the browser's width on
 * the View's key: where the width goes is decided when the drag starts, not when the
 * pointer happens to come up.
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
  type PanelKind,
} from "./viewerPersistence";

export interface PanelResize {
  /** The width to lay the slot out at: the live drag if one is in flight, else the
   *  stored preference for whichever panel is currently in the slot. */
  liveWidth: () => number;
  /** `onResize` for the splitter — `dx` is the pointer's delta, and the panel sits on
   *  the right, so a rightward drag narrows it. */
  onResize: (dx: number) => void;
  /** `onResizeEnd` for the splitter: persist and drop the override. */
  onResizeEnd: () => void;
}

/** The drag controller for the viewport slot. `panelKind` reports which panel is in the
 *  slot *now* — it is what the width is stored against. */
export function createPanelResize(panelKind: () => PanelKind): PanelResize {
  const [drag, setDrag] = createSignal<{
    kind: PanelKind;
    width: number;
  } | null>(null);

  return {
    liveWidth: () => drag()?.width ?? panelWidth(panelKind()),
    onResize: (dx: number) => {
      const started = drag();
      const kind = started?.kind ?? panelKind();
      const from = started?.width ?? panelWidth(kind);
      setDrag({ kind, width: clampWidth(from - dx, kind) });
    },
    onResizeEnd: () => {
      const settled = drag();
      if (settled) setPanelWidth(settled.kind, settled.width);
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
