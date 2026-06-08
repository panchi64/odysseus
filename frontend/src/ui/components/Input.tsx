import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";
import { type IconName } from "../icons/registry";

export interface InputProps extends JSX.InputHTMLAttributes<HTMLInputElement> {
  /** Uppercase field label rendered above the control. */
  label?: string;
  /** Alert/validation state. */
  invalid?: boolean;
  /** Dim helper or error text below the control. */
  hint?: string;
  /** Leading glyph rendered inside the control (e.g. `search`). */
  leading?: IconName;
}

const fieldClass =
  "w-full bg-surface border px-2 h-8 rounded-ctl text-body font-mono text-bright placeholder:text-dim outline-none transition-colors focus:border-bright disabled:opacity-40 disabled:cursor-not-allowed";

/** Single-line text control. */
export function Input(props: InputProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "label",
    "invalid",
    "hint",
    "leading",
    "class",
  ]);
  return (
    <label class="flex flex-col gap-1">
      <Show when={local.label}>
        <Text variant="label" tone="dim">
          {local.label}
        </Text>
      </Show>
      <div class="relative">
        <Show when={local.leading}>
          <Icon
            name={local.leading!}
            size={14}
            class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-dim"
          />
        </Show>
        <input
          class={cx(
            fieldClass,
            local.leading && "pl-8",
            local.invalid ? "border-alert" : "border-line",
            local.class,
          )}
          aria-invalid={local.invalid || undefined}
          {...rest}
        />
      </div>
      <Show when={local.hint}>
        <Text variant="micro" tone={local.invalid ? "alert" : "dim"}>
          {local.hint}
        </Text>
      </Show>
    </label>
  );
}

export { fieldClass };
