import { For, Show, createMemo, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";
import { Popover } from "./Popover";

export interface SelectOption {
  value: string;
  label: string;
  /** A dim line under the label, in the menu only — the trigger stays one line. */
  description?: string;
  /** A background class (`bg-warn`, …) for a small square before the label, on the
   *  trigger and in the menu, for options that carry a colour of their own. */
  swatch?: string;
}

function Swatch(props: { class: string }): JSX.Element {
  return <span aria-hidden class={cx("size-2 shrink-0", props.class)} />;
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
  const selected = createMemo(() =>
    props.options.find((o) => o.value === props.value),
  );
  const selectedLabel = () => selected()?.label;

  return (
    <div class={cx("flex flex-col gap-1", props.class)}>
      <Show when={props.label}>
        <Text variant="label" tone="dim">
          {props.label}
        </Text>
      </Show>
      <Popover
        block
        // A described row is two to three lines tall, so the cap that fits ~8 plain
        // rows would scroll a five-row described menu; `Popover` still clamps to the
        // viewport when even this doesn't fit.
        panelClass={cx(
          "overflow-y-auto py-1",
          props.options.some((o) => o.description)
            ? "max-h-[28rem]"
            : "max-h-72",
        )}
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
            <Show when={selected()?.swatch}>
              {(swatch) => <Swatch class={swatch()} />}
            </Show>
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
                      "flex w-full flex-col gap-0.5 px-2 py-1.5 text-left transition-colors hover:bg-raised",
                      opt.value === props.value && "bg-raised",
                    )}
                  >
                    <span class="flex items-center gap-2">
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
                      <Show when={opt.swatch}>
                        {(swatch) => <Swatch class={swatch()} />}
                      </Show>
                      {/* The option sets its own width — no `truncate`. The panel is
                          floored at the field's width and grows to its contents, so
                          an option clipped here would be clipped by nothing: the room
                          to render it in full is always there for the asking. The
                          trigger above still truncates, because that one *is* bounded
                          by the field. */}
                      <Text
                        variant="body"
                        tone={opt.value === props.value ? "bright" : "default"}
                        class="whitespace-nowrap"
                      >
                        {opt.label}
                      </Text>
                    </span>
                    {/* The description wraps where the label doesn't: it is a
                        sentence, and letting it set the panel's width would stretch
                        every menu to its longest one. Indented to sit under the
                        label — past the check, and the swatch when there is one.
                        The micro step in the sans face rather than `Text`'s mono
                        `micro`: it is fine print, but it is still a sentence. */}
                    <Show when={opt.description}>
                      <span
                        class={cx(
                          "max-w-60 font-sans text-micro text-dim",
                          opt.swatch ? "pl-9" : "pl-5",
                        )}
                      >
                        {opt.description}
                      </span>
                    </Show>
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
