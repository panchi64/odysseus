import { For, Show, createSignal, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: IconProps["name"];
  danger?: boolean;
  disabled?: boolean;
}

export interface MenuProps {
  /** The clickable trigger (e.g. a Button or icon). */
  trigger: JSX.Element;
  items: MenuItem[];
  /** Horizontal alignment of the panel. Default right. */
  align?: "left" | "right";
  class?: string;
}

/** Dropdown menu. Closes on item select or backdrop click. Instant reveal. */
export function Menu(props: MenuProps): JSX.Element {
  const [local] = splitProps(props, ["trigger", "items", "align", "class"]);
  const [open, setOpen] = createSignal(false);
  return (
    <div class={cx("relative inline-flex", local.class)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        class="inline-flex"
      >
        {local.trigger}
      </button>
      <Show when={open()}>
        <div class="fixed inset-0 z-40" onClick={() => setOpen(false)} />
        <div
          role="menu"
          class={cx(
            "absolute top-full z-50 mt-1 min-w-40 border border-line bg-surface py-1",
            local.align === "left" ? "left-0" : "right-0",
          )}
        >
          <For each={local.items}>
            {(item) => (
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
                class={cx(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-raised disabled:opacity-40 disabled:cursor-not-allowed",
                )}
              >
                <Show when={item.icon}>
                  <Icon
                    name={item.icon!}
                    size={12}
                    class={item.danger ? "text-alert" : "text-dim"}
                  />
                </Show>
                <Text variant="label" tone={item.danger ? "alert" : "default"}>
                  {item.label}
                </Text>
              </button>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
}
