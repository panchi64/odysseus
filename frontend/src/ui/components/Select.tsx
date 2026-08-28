import { For, Show, createMemo, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";
import { Popover } from "./Popover";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  /** Uppercase field label rendered above the control. */
  label?: string;
  options: SelectOption[];
  value?: string;
  /** Value-based change handler (consistent with Checkbox/Toggle), so callers
   *  can pass a string setter directly: `onChange={setModel}`. */
  onChange?: (value: string) => void;
  invalid?: boolean;
  /** Dim helper or error text below the control. */
  hint?: string;
  disabled?: boolean;
  /** Trigger text when no option matches the current value. */
  placeholder?: string;
  /** Layout glue (width/height/margins) merged onto the field wrapper. */
  class?: string;
  "aria-label"?: string;
}

/** Dropdown select whose option list is rendered by the frontend (the shared
 *  Popover shell + Combobox-style rows), so the menu matches the design system
 *  instead of the OS-native control. Same value/onChange contract as before. */
export function Select(props: SelectProps): JSX.Element {
  const selectedLabel = createMemo(
    () => props.options.find((o) => o.value === props.value)?.label,
  );

  return (
    <div class={cx("flex flex-col gap-1", props.class)}>
      <Show when={props.label}>
        <Text variant="label" tone="dim">
          {props.label}
        </Text>
      </Show>
      <Popover
        block
        panelClass="max-h-72 overflow-y-auto py-1"
        trigger={({ open, setOpen }) => (
          <button
            type="button"
            disabled={props.disabled}
            aria-label={props["aria-label"] ?? props.label}
            aria-haspopup="listbox"
            aria-expanded={open()}
            aria-invalid={props.invalid || undefined}
            onClick={() => setOpen(!open())}
            class={cx(
              // Matches Input/Combobox: a filled control, no bright edge on
              // focus or open. Only `invalid` draws a border, because that is
              // the one state that has to interrupt.
              "flex h-8 w-full items-center gap-2 rounded-ctl border bg-raised px-3 text-left outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              props.invalid ? "border-alert" : "border-transparent",
            )}
          >
            <Text
              variant="body"
              tone={selectedLabel() ? "bright" : "dim"}
              class="min-w-0 flex-1 truncate"
            >
              {selectedLabel() ?? props.placeholder ?? "Select…"}
            </Text>
            <Icon name="chevron-down" size={12} class="shrink-0 text-dim" />
          </button>
        )}
        panel={({ close }) => {
          const pick = (value: string) => {
            props.onChange?.(value);
            close();
          };
          return (
            <div role="listbox">
              <For each={props.options}>
                {(opt) => (
                  <button
                    type="button"
                    role="option"
                    aria-selected={opt.value === props.value}
                    onClick={() => pick(opt.value)}
                    class={cx(
                      "flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors hover:bg-raised",
                      opt.value === props.value && "bg-raised",
                    )}
                  >
                    <Icon
                      name="check"
                      size={12}
                      class={cx(
                        "shrink-0",
                        opt.value === props.value
                          ? "text-nominal"
                          : "opacity-0",
                      )}
                    />
                    <Text
                      variant="body"
                      tone={opt.value === props.value ? "bright" : "default"}
                      class="min-w-0 truncate"
                    >
                      {opt.label}
                    </Text>
                  </button>
                )}
              </For>
            </div>
          );
        }}
      />
      <Show when={props.hint}>
        <Text variant="micro" tone={props.invalid ? "alert" : "dim"}>
          {props.hint}
        </Text>
      </Show>
    </div>
  );
}
