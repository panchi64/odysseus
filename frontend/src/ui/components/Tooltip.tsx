import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface TooltipProps {
  /** Tooltip text. */
  label: string;
  /** Edge to place the tip. Default top. */
  side?: "top" | "bottom" | "left" | "right";
  class?: string;
  children: JSX.Element;
}

const sideClass = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1",
  left: "right-full top-1/2 -translate-y-1/2 mr-1",
  right: "left-full top-1/2 -translate-y-1/2 ml-1",
} as const;

/** Hover/focus tooltip. CSS-only reveal (instant), no JS timers. */
export function Tooltip(props: TooltipProps): JSX.Element {
  const [local] = splitProps(props, ["label", "side", "class", "children"]);
  return (
    <span class={cx("group/tip relative inline-flex", local.class)}>
      {local.children}
      <span
        role="tooltip"
        class={cx(
          "pointer-events-none absolute z-50 hidden whitespace-nowrap border border-line bg-raised px-2 py-1 text-micro uppercase tracking-label text-bright group-hover/tip:block group-focus-within/tip:block",
          sideClass[local.side ?? "top"],
        )}
      >
        {local.label}
      </span>
    </span>
  );
}
