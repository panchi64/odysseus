import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone } from "../primitives/Text";

export interface FieldProps {
  label: string;
  /** Value. Strings render as body text; pass JSX for richer content. */
  value?: JSX.Element;
  /** Layout: label above value (default) or label left of value. */
  orientation?: "stack" | "row";
  /** Value tone. Defaults to bright (the active value). */
  tone?: TextTone;
  class?: string;
}

/** Label + value atom — the system's smallest unit (§6.1). */
export function Field(props: FieldProps): JSX.Element {
  const [local] = splitProps(props, [
    "label",
    "value",
    "orientation",
    "tone",
    "class",
  ]);
  const isRow = () => local.orientation === "row";
  return (
    <div
      class={cx(
        "flex gap-1",
        isRow() ? "flex-row items-baseline justify-between" : "flex-col",
        local.class,
      )}
    >
      <Text variant="label" tone="dim">
        {local.label}
      </Text>
      <Text variant="body" tone={local.tone ?? "bright"}>
        {local.value}
      </Text>
    </div>
  );
}
