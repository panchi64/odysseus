import { For, Show, type JSX } from "solid-js";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: IconProps["name"];
  danger?: boolean;
  disabled?: boolean;
  /** Draw a rule above this item — for separating a destructive action, or a group
   *  that acts on something different from the group before it. A menu whose items
   *  all act on the same thing needs none, which is why it is opt-in. */
  separated?: boolean;
}

/** The rows inside a menu panel, shared by `Menu` and `ContextMenu`.
 *
 *  The two differ only in what opens them — a trigger button versus a right-click —
 *  and forking the list to say that would put the `danger` tone, the disabled
 *  treatment, the icon sizing and the menu/menuitem roles in two places that drift.
 *  A caller supplies the items and a way to dismiss; everything else is here. */
export function MenuItems(props: {
  items: MenuItem[];
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
                // Close before acting: the action frequently removes the very row the
                // menu was opened from, and a dismissal issued after that is racing an
                // unmount for no reason.
                props.close();
                item.onSelect();
              }}
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-raised disabled:opacity-40 disabled:cursor-not-allowed"
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
