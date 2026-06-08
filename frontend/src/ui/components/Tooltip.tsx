import { Show, createSignal, onCleanup, splitProps, type JSX } from "solid-js";
import { Portal } from "solid-js/web";
import { cx } from "../cx";

export interface TooltipProps {
  /** Tooltip text. */
  label: string;
  /** Edge to place the tip. Default top. */
  side?: "top" | "bottom" | "left" | "right";
  /** Hover-intent delay before the tip shows, in ms. Only applies in `float`
   *  mode. Default 0 (instant). */
  delay?: number;
  /** Render the tip in a portal with fixed positioning so it escapes
   *  overflow-clipping ancestors (e.g. a scrolling sidebar). Enables `delay`. */
  float?: boolean;
  /** Render the label as normal-case prose instead of the default uppercase
   *  HUD label — for full-sentence explanations (see `InfoHint`). */
  prose?: boolean;
  class?: string;
  children: JSX.Element;
}

const sideClass = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1",
  left: "right-full top-1/2 -translate-y-1/2 mr-1",
  right: "left-full top-1/2 -translate-y-1/2 ml-1",
} as const;

const tipChrome =
  "pointer-events-none border border-line bg-raised px-2 py-1 text-micro text-bright";
const tipCase = (prose?: boolean) =>
  prose ? "tracking-normal" : "uppercase tracking-label";

/** Hover/focus tooltip. Default is a CSS-only instant reveal positioned
 *  relative to the trigger. `float` switches to a portaled, fixed-positioned
 *  tip (with optional `delay`) that can't be clipped by scrolling ancestors. */
export function Tooltip(props: TooltipProps): JSX.Element {
  const [local] = splitProps(props, [
    "label",
    "side",
    "delay",
    "float",
    "prose",
    "class",
    "children",
  ]);

  if (!local.float) {
    return (
      <span class={cx("group/tip relative inline-flex", local.class)}>
        {local.children}
        <span
          role="tooltip"
          class={cx(
            tipChrome,
            tipCase(local.prose),
            "absolute z-50 hidden group-hover/tip:block group-focus-within/tip:block",
            local.prose ? "max-w-56 whitespace-normal" : "whitespace-nowrap",
            sideClass[local.side ?? "top"],
          )}
        >
          {local.label}
        </span>
      </span>
    );
  }

  // Floating mode: position from the trigger's viewport rect, render in a portal.
  let ref: HTMLSpanElement | undefined;
  let timer: number | undefined;
  const [pos, setPos] = createSignal<{ x: number; y: number } | null>(null);
  const side = () => local.side ?? "top";

  const show = () => {
    if (!ref) return;
    const r = ref.getBoundingClientRect();
    const gap = 6;
    switch (side()) {
      case "right":
        setPos({ x: r.right + gap, y: r.top + r.height / 2 });
        break;
      case "left":
        setPos({ x: r.left - gap, y: r.top + r.height / 2 });
        break;
      case "bottom":
        setPos({ x: r.left + r.width / 2, y: r.bottom + gap });
        break;
      default:
        setPos({ x: r.left + r.width / 2, y: r.top - gap });
    }
  };
  const open = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(show, local.delay ?? 0);
  };
  const close = () => {
    window.clearTimeout(timer);
    setPos(null);
  };
  onCleanup(() => window.clearTimeout(timer));

  const transform = () => {
    switch (side()) {
      case "right":
        return "translateY(-50%)";
      case "left":
        return "translate(-100%, -50%)";
      case "bottom":
        return "translateX(-50%)";
      default:
        return "translate(-50%, -100%)";
    }
  };

  return (
    <span
      ref={ref}
      class={cx("relative", local.class)}
      onMouseEnter={open}
      onMouseLeave={close}
      onFocusIn={open}
      onFocusOut={close}
    >
      {local.children}
      <Show when={pos()}>
        {(p) => (
          <Portal>
            <span
              role="tooltip"
              class={cx(
                tipChrome,
                tipCase(local.prose),
                "fixed z-50 max-w-56 whitespace-normal",
              )}
              style={{
                left: `${p().x}px`,
                top: `${p().y}px`,
                transform: transform(),
              }}
            >
              {local.label}
            </span>
          </Portal>
        )}
      </Show>
    </span>
  );
}
