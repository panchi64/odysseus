import { For, Show, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: IconProps["name"];
  danger?: boolean;
  disabled?: boolean;
  /** Draw a divider above this item — for separating a destructive action, or a
   *  group that acts on something different from the group before it. */
  separated?: boolean;
}

/**
 * The rows inside a menu, wherever that menu is anchored.
 *
 * Shared by the dropdown `Menu` and the pointer-positioned `ContextMenu`, which
 * differ only in *where* they appear: the same actions reached two ways should not
 * be two sets of markup that drift into looking like two different menus.
 */
export function MenuItemList(props: {
  items: MenuItem[];
  /** Dismiss the containing surface. Called before the item's own handler, so an
   *  action that changes what is underneath does not run with the menu still over
   *  it. */
  close: () => void;
}): JSX.Element {
  return (
    <div role="menu">
      <For each={props.items}>
        {(item) => (
          <>
            <Show when={item.separated}>
              <div class="my-1 h-px bg-line" role="separator" />
            </Show>
            <button
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                props.close();
                item.onSelect();
              }}
              class={cx(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-raised disabled:cursor-not-allowed disabled:opacity-40",
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
          </>
        )}
      </For>
    </div>
  );
}
