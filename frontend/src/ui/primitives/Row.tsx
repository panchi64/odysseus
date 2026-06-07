import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { gapClass, type GapStep } from "./Stack";

export interface RowProps extends JSX.HTMLAttributes<HTMLDivElement> {
  /** Horizontal gap between children, in grid steps. */
  gap?: GapStep;
  /** Cross-axis alignment. Defaults to center. */
  align?: "start" | "center" | "end" | "baseline" | "stretch";
  /** Main-axis distribution. */
  justify?: "start" | "center" | "end" | "between";
  /** Allow wrapping. */
  wrap?: boolean;
}

const alignClass = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  baseline: "items-baseline",
  stretch: "items-stretch",
} as const;

const justifyClass = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
} as const;

/** Horizontal flex row with a token-backed gap. */
export function Row(props: RowProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "gap",
    "align",
    "justify",
    "wrap",
    "class",
  ]);
  return (
    <div
      class={cx(
        "flex flex-row",
        alignClass[local.align ?? "center"],
        local.justify && justifyClass[local.justify],
        local.wrap && "flex-wrap",
        gapClass[local.gap ?? 0],
        local.class,
      )}
      {...rest}
    />
  );
}
