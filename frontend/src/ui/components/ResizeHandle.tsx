import { type JSX } from "solid-js";
import { cx } from "../cx";

export interface ResizeHandleProps {
  /** Fired with the horizontal pointer delta (px, positive = moved right) as the
   *  handle is dragged or nudged with the arrow keys. The caller maps the delta
   *  onto whichever pane it owns. */
  onResize: (deltaX: number) => void;
  /** Fired once when a drag/nudge settles — the moment to persist the new size,
   *  so the live drag doesn't write on every move. */
  onResizeEnd?: () => void;
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

/** A vertical splitter between two panes: a hairline that brightens on
 *  hover/focus, with a wider invisible hit area so it's easy to grab. Mechanical,
 *  no eased motion (design §8). Drag with the pointer or nudge with ← / →. */
export function ResizeHandle(props: ResizeHandleProps): JSX.Element {
  const STEP = 16;
  const onPointerDown = (e: PointerEvent) => {
    e.preventDefault();
    const target = e.currentTarget as HTMLElement;
    let lastX = e.clientX;
    target.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      props.onResize(ev.clientX - lastX);
      lastX = ev.clientX;
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
    if (e.key === "ArrowLeft") props.onResize(-STEP);
    else if (e.key === "ArrowRight") props.onResize(STEP);
    else return;
    e.preventDefault();
    props.onResizeEnd?.();
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={props["aria-label"] ?? "Resize panel"}
      tabindex={0}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
      class={cx(
        "group relative w-1.5 shrink-0 cursor-col-resize touch-none select-none",
        props.class,
      )}
    >
      {/* The resting paint is the only thing `divider` changes — a `hover`
          splitter still reserves its width, so revealing the line shifts
          nothing either side of it. */}
      <span
        class={cx(
          "absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors group-hover:bg-bright group-focus-visible:bg-bright",
          props.divider === "hover" ? "bg-transparent" : "bg-line",
        )}
      />
    </div>
  );
}
