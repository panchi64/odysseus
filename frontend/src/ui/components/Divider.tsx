import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface DividerProps {
  orientation?: "horizontal" | "vertical";
  class?: string;
}

/** Hairline rule — the "free ink" that enforces structure (§2 borders). */
export function Divider(props: DividerProps): JSX.Element {
  const [local] = splitProps(props, ["orientation", "class"]);
  return (
    <div
      role="separator"
      class={cx(
        local.orientation === "vertical"
          ? "w-px self-stretch bg-line"
          : "h-px w-full bg-line",
        local.class,
      )}
    />
  );
}
