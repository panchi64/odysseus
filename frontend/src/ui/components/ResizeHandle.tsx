import { type JSX } from "solid-js";
import { cx } from "../cx";

/** Which way the splitter's own hairline runs — not which way it drags.
 *
 *  This is ARIA's sense of the word (`aria-orientation` on a `separator`
 *  describes the separator, not the gesture), and the two are always
 *  perpendicular: a `vertical` rule sits between two side-by-side panes and
 *  drags left/right; a `horizontal` rule sits between two stacked panes and
 *  drags up/down. Naming it after the gesture instead would read more
 *  naturally in the caller and disagree with the attribute it sets. */
export type ResizeOrientation = "vertical" | "horizontal";

export interface ResizeHandleProps {
  /** Fired with the pointer delta along the drag axis (px) as the handle is
   *  dragged or nudged with the arrow keys — X for a `vertical` handle
   *  (positive = moved right), Y for a `horizontal` one (positive = moved
   *  down). The caller maps the delta onto whichever pane it owns. */
  onResize: (delta: number) => void;
  /** Fired once when a drag/nudge settles — the moment to persist the new size,
   *  so the live drag doesn't write on every move. */
  onResizeEnd?: () => void;
  /** Defaults to `vertical` — the side-by-side case, which is every caller the
   *  splitter had before panes could stack. */
  orientation?: ResizeOrientation;
  "aria-label"?: string;
  /** How the splitter's own hairline behaves at rest.
   *
   *  `line` (default) always draws it — for a handle that **is** the boundary,
   *  like the nav rail's, where the rail carries no surface of its own and this
   *  hairline is the only thing separating it from the page.
   *
   *  `hover` keeps it invisible until pointed at or focused, for a handle
   *  sitting beside something that already draws its own edge. The View panel is
   *  the case: it brackets itself with a frame, and a second rule three pixels
   *  outside that one does not read as a splitter — it reads as the doubled
   *  border §7 exists to stop. The hit area, the drag and the keyboard nudge are
   *  unchanged; only the resting paint goes. */
  divider?: "line" | "hover";
  class?: string;
}

/** A splitter between two panes: a hairline that brightens on hover/focus, with
 *  a wider invisible hit area so it's easy to grab. Mechanical, no eased motion
 *  (design §8). Drag with the pointer, or nudge with ← / → (vertical) or
 *  ↑ / ↓ (horizontal). */
export function ResizeHandle(props: ResizeHandleProps): JSX.Element {
  const STEP = 16;
  const vertical = (): boolean =>
    (props.orientation ?? "vertical") === "vertical";
  /* Read the axis off the event rather than branching at the call sites, so the
     pointer and keyboard paths cannot disagree about which one they are on. */
  const axis = (e: { clientX: number; clientY: number }): number =>
    vertical() ? e.clientX : e.clientY;

  const onPointerDown = (e: PointerEvent) => {
    e.preventDefault();
    const target = e.currentTarget as HTMLElement;
    let last = axis(e);
    target.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      props.onResize(axis(ev) - last);
      last = axis(ev);
    };
    // `pointercancel` settles the drag too, not just `pointerup`. The browser fires
    // it instead when the gesture is taken away (a touch becoming a system scroll, the
    // capture being lost), and a caller that holds live drag state until it is told the
    // drag ended would otherwise hold it forever.
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      props.onResizeEnd?.();
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    const [back, forward] = vertical()
      ? ["ArrowLeft", "ArrowRight"]
      : ["ArrowUp", "ArrowDown"];
    if (e.key === back) props.onResize(-STEP);
    else if (e.key === forward) props.onResize(STEP);
    else return;
    e.preventDefault();
    props.onResizeEnd?.();
  };
  return (
    <div
      role="separator"
      aria-orientation={vertical() ? "vertical" : "horizontal"}
      aria-label={props["aria-label"] ?? "Resize panel"}
      tabindex={0}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
      class={cx(
        "group relative shrink-0 touch-none select-none",
        vertical() ? "w-1.5 cursor-col-resize" : "h-1.5 cursor-row-resize",
        props.class,
      )}
    >
      {/* The resting paint is the only thing `divider` changes — a `hover`
          splitter still reserves its width, so revealing the line shifts
          nothing either side of it. */}
      <span
        class={cx(
          "absolute transition-colors group-hover:bg-bright group-focus-visible:bg-bright",
          vertical()
            ? "inset-y-0 left-1/2 w-px -translate-x-1/2"
            : "inset-x-0 top-1/2 h-px -translate-y-1/2",
          props.divider === "hover" ? "bg-transparent" : "bg-line",
        )}
      />
    </div>
  );
}
