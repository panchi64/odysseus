import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone } from "../primitives/Text";

export interface ReadoutProps {
  /** The hero value (tabular). */
  value: JSX.Element;
  /** Dim label beneath/above the value. */
  label?: string;
  /** Optional trailing unit, rendered dim and small next to the value. */
  unit?: string;
  /** `lg` = hero (one per screen). `md` = secondary readout. */
  size?: "md" | "lg";
  tone?: TextTone;
  /** Label position relative to the value. */
  labelPosition?: "top" | "bottom";
  class?: string;
}

/** The hero numeric value (§6.4). Tabular, bright, one `lg` per screen. */
export function Readout(props: ReadoutProps): JSX.Element {
  const [local] = splitProps(props, [
    "value",
    "label",
    "unit",
    "size",
    "tone",
    "labelPosition",
    "class",
  ]);
  const valueVariant = () => (local.size === "md" ? "readout" : "readout-lg");
  const label = (
    <Show when={local.label}>
      <Text variant="label" tone="dim">
        {local.label}
      </Text>
    </Show>
  );
  return (
    <div class={cx("flex flex-col gap-1", local.class)}>
      <Show when={local.labelPosition !== "bottom"}>{label}</Show>
      <div class="flex items-baseline gap-1">
        <Text variant={valueVariant()} tone={local.tone ?? "bright"}>
          {local.value}
        </Text>
        <Show when={local.unit}>
          <Text variant="label" tone="dim">
            {local.unit}
          </Text>
        </Show>
      </div>
      <Show when={local.labelPosition === "bottom"}>{label}</Show>
    </div>
  );
}
