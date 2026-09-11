import { splitProps, type JSX } from "solid-js";
import { MenuItemList, type MenuItem } from "./menuItems";
import { Popover } from "./Popover";

export type { MenuItem };

export interface MenuProps {
  /** The clickable trigger (e.g. a Button or icon). */
  trigger: JSX.Element;
  items: MenuItem[];
  /** Horizontal alignment of the panel. Default right. */
  align?: "left" | "right";
  class?: string;
}

/** Dropdown menu, anchored to its trigger. Closes on item select, backdrop click,
 *  or Escape. Instant reveal. Built on the shared Popover shell.
 *
 *  Its rows live in `menuItems.tsx`, shared with `ContextMenu` — the two differ in
 *  where they appear, not in what a menu looks like. */
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
      panel={({ close }) => <MenuItemList items={local.items} close={close} />}
    />
  );
}
