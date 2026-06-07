import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

/** Spacing steps that exist on the 4px grid. */
export type GapStep = 0 | 1 | 2 | 3 | 4 | 6 | 8;

const gapClass: Record<GapStep, string> = {
  0: "gap-0",
  1: "gap-1",
  2: "gap-2",
  3: "gap-3",
  4: "gap-4",
  6: "gap-6",
  8: "gap-8",
};

export interface StackProps extends JSX.HTMLAttributes<HTMLDivElement> {
  /** Vertical gap between children, in grid steps. */
  gap?: GapStep;
}

/** Vertical flex column with a token-backed gap. */
export function Stack(props: StackProps): JSX.Element {
  const [local, rest] = splitProps(props, ["gap", "class"]);
  return (
    <div
      class={cx("flex flex-col", gapClass[local.gap ?? 0], local.class)}
      {...rest}
    />
  );
}

export { gapClass };
