import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone } from "../primitives/Text";

export interface ProgressBarProps {
  /** 0–100. Omit for an indeterminate "UPDATING…" band (still no spinner). */
  value?: number;
  label?: string;
  /** Accent of the fill. Defaults to nominal. */
  tone?: Extract<TextTone, "nominal" | "warn" | "alert" | "info">;
  /** Show the numeric percentage (tabular) on the right. */
  showValue?: boolean;
  class?: string;
}

const fillBg: Record<NonNullable<ProgressBarProps["tone"]>, string> = {
  nominal: "bg-nominal",
  warn: "bg-warn",
  alert: "bg-alert",
  info: "bg-info",
};

/** Determinate progress as a mechanical bar — used for downloads, uploads,
 *  research rounds. Never a spinner. */
export function ProgressBar(props: ProgressBarProps): JSX.Element {
  const [local] = splitProps(props, [
    "value",
    "label",
    "tone",
    "showValue",
    "class",
  ]);
  const clamped = () => Math.max(0, Math.min(100, local.value ?? 0));
  const determinate = () => local.value !== undefined;
  return (
    <div class={cx("flex flex-col gap-1", local.class)}>
      <Show when={local.label || local.showValue}>
        <div class="flex items-baseline justify-between gap-2">
          <Show when={local.label}>
            <Text variant="label" tone="dim">
              {local.label}
            </Text>
          </Show>
          <Show when={local.showValue && determinate()}>
            <Text variant="label" tone="bright">
              {clamped().toFixed(0)}%
            </Text>
          </Show>
        </div>
      </Show>
      <div
        class="h-1 w-full bg-raised"
        role="progressbar"
        aria-valuenow={determinate() ? clamped() : undefined}
      >
        <div
          class={cx(
            "h-full transition-[width]",
            fillBg[local.tone ?? "nominal"],
          )}
          style={{ width: determinate() ? `${clamped()}%` : "100%" }}
        />
      </div>
    </div>
  );
}
