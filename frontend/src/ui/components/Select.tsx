import { For, Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<
  JSX.SelectHTMLAttributes<HTMLSelectElement>,
  "children" | "onChange" | "value"
> {
  label?: string;
  options: SelectOption[];
  value?: string;
  /** Value-based change handler (consistent with Checkbox/Toggle), so callers
   *  can pass a string setter directly: `onChange={setModel}`. */
  onChange?: (value: string) => void;
  invalid?: boolean;
  hint?: string;
}

/** Native select styled to the system, with a registry chevron. */
export function Select(props: SelectProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "label",
    "options",
    "value",
    "onChange",
    "invalid",
    "hint",
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
        <select
          class={cx(
            "w-full appearance-none bg-surface border pl-2 pr-7 h-8 rounded-ctl text-body font-mono text-bright outline-none transition-colors focus:border-bright disabled:opacity-40",
            local.invalid ? "border-alert" : "border-line",
            local.class,
          )}
          value={local.value}
          onChange={(e) => local.onChange?.(e.currentTarget.value)}
          aria-invalid={local.invalid || undefined}
          {...rest}
        >
          <For each={local.options}>
            {(opt) => <option value={opt.value}>{opt.label}</option>}
          </For>
        </select>
        <Icon
          name="chevron-down"
          size={12}
          class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-dim"
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
