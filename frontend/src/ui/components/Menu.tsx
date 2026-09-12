import { splitProps, type JSX } from "solid-js";
import { Popover } from "./Popover";
import { MenuItems, type MenuItem } from "./menuItems";

export type { MenuItem };

export interface MenuProps {
  /** The clickable trigger (e.g. a Button or icon). */
  trigger: JSX.Element;
  items: MenuItem[];
  /** Horizontal alignment of the panel. Default right. */
  align?: "left" | "right";
  class?: string;
}

/** Dropdown menu. Closes on item select, backdrop click, or Escape. Instant
 *  reveal. Built on the shared Popover shell, with the rows from `MenuItems` so it
 *  and `ContextMenu` cannot look like two different menus. */
export function Menu(props: MenuProps): JSX.Element {
  const [local] = splitProps(props, ["trigger", "items", "align", "class"]);
  return (
    <Popover
      class={local.class}
      align={local.align ?? "right"}
      panelClass="min-w-40 py-1"
      trigger={({ open, setOpen }) => (
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open()}
          onClick={() => setOpen(true)}
          class="inline-flex"
        >
          {local.trigger}
        </button>
      )}
      panel={({ close }) => <MenuItems items={local.items} close={close} />}
    />
  );
}
