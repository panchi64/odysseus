import { For, Show, type JSX } from "solid-js";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";
import { Frames } from "./Frames";
import { Tooltip } from "./Tooltip";

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: IconProps["name"];
  danger?: boolean;
  disabled?: boolean;
  /** An action this row started is still running. Swaps the icon for the throbber and
   *  refuses a second press. A menu closes on select, so without this the only evidence
   *  a slow action was ever started is that the row is dimmed the *next* time the menu
   *  is opened — and a second press meanwhile is a duplicate request. */
  pending?: boolean;
  /** Why this row is off, for the operator who just clicked a dimmed row and got
   *  nothing. A greyed control with no explanation is indistinguishable from a broken
   *  one, which is the single most common way a working feature reads as bug. Shown as
   *  a tooltip; ignored on an enabled row, which explains itself by working. */
  hint?: string;
  /** Draw a rule above this item — for separating a destructive action, or a group
   *  that acts on something different from the group before it. A menu whose items
   *  all act on the same thing needs none, which is why it is opt-in. */
  separated?: boolean;
}

/** One row. Split out of the list so a row can carry its own wrapper — the tooltip a
 *  `hint` needs has to sit *outside* the button, since a disabled control emits no
 *  pointer events of its own and a tip bound to it would never open. */
function Row(props: { item: MenuItem; close: () => void }): JSX.Element {
  const off = (): boolean => !!props.item.disabled || !!props.item.pending;
  const button = (
    <button
      type="button"
      role="menuitem"
      disabled={off()}
      aria-busy={props.item.pending || undefined}
      onClick={() => {
        // Close before acting: the action frequently removes the very row the
        // menu was opened from, and a dismissal issued after that is racing an
        // unmount for no reason.
        props.close();
        props.item.onSelect();
      }}
      class="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-raised disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <Show when={!props.item.pending} fallback={<Frames class="text-info" />}>
        <Show when={props.item.icon}>
          <Icon
            name={props.item.icon!}
            size={12}
            class={props.item.danger ? "text-alert" : "text-dim"}
          />
        </Show>
      </Show>
      <Text variant="label" tone={props.item.danger ? "alert" : "default"}>
        {props.item.label}
      </Text>
    </button>
  );
  return (
    <Show when={props.item.hint && off()} fallback={button}>
      <Tooltip label={props.item.hint!} side="left">
        {button}
      </Tooltip>
    </Show>
  );
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
            <Row item={item} close={props.close} />
          </>
        )}
      </For>
    </div>
  );
}
