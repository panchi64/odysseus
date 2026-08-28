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
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      props.onResizeEnd?.();
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
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
      <span class="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line transition-colors group-hover:bg-bright group-focus-visible:bg-bright" />
    </div>
  );
}
