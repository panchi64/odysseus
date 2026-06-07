import { Dynamic } from "solid-js/web";
import type { JSX } from "solid-js";
import { cx } from "../cx";
import { icons, type IconName } from "../icons/registry";

export interface IconProps {
  name: IconName;
  /** Pixel size of the square box. Defaults to 16 (the icon grid unit). */
  size?: number;
  /** Stroke width. Defaults to 1.5 per the design system. */
  stroke?: number;
  class?: string;
  "aria-label"?: string;
}

/**
 * Renders a registry icon as a 1.5px stroke SVG in currentColor. Color comes
 * from the surrounding text color (a token), never a hardcoded value.
 */
export function Icon(props: IconProps): JSX.Element {
  const size = () => props.size ?? 16;
  return (
    <svg
      width={size()}
      height={size()}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      stroke-width={props.stroke ?? 1.5}
      stroke-linecap="round"
      stroke-linejoin="round"
      class={cx("inline-block shrink-0", props.class)}
      role={props["aria-label"] ? "img" : "presentation"}
      aria-label={props["aria-label"]}
      aria-hidden={props["aria-label"] ? undefined : "true"}
    >
      <Dynamic component={icons[props.name]} />
    </svg>
  );
}
