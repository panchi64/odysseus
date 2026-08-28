import { For, Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";
import { Popover } from "./Popover";

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

/** Dropdown menu. Closes on item select, backdrop click, or Escape. Instant
 *  reveal. Built on the shared Popover shell. */
export function Menu(props: MenuProps): JSX.Element {
  const [local] = splitProps(props, ["trigger", "items", "align", "class"]);
  return (
    <Popover
      class={local.class}
      align={local.align ?? "right"}
      panelClass="min-w-40 py-1"
      trigger={({ setOpen }) => (
        <button type="button" onClick={() => setOpen(true)} class="inline-flex">
          {local.trigger}
        </button>
      )}
      panel={({ close }) => (
        <div role="menu">
          <For each={local.items}>
            {(item) => (
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  close();
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
      )}
    />
  );
}
