import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import { Portal } from "solid-js/web";
import { cx } from "../cx";
import { MenuItemList, type MenuItem } from "./menuItems";

/** Kept clear of the window edge so a menu opened in a corner is never clipped. */
const EDGE_MARGIN = 8;
/** Enough to place the panel before it has been measured. Real width is read after
 *  mount and the position corrected in the same frame. */
const ASSUMED = { width: 176, height: 200 };

export interface ContextMenuProps {
  /** Read when the menu opens, not when it is defined — so the actions can depend
   *  on what is true at the moment of the right-click. An empty list suppresses the
   *  menu entirely and lets the browser's own through. */
  items: () => MenuItem[];
  children: JSX.Element;
  /** Layout glue for the region that listens. */
  class?: string;
}

/**
 * A menu at the pointer, for acting on the thing under it.
 *
 * **Not `Menu` with a different trigger.** A dropdown is anchored to a control the
 * operator clicked and is positioned against it; this is anchored to a *point*, and
 * the thing it acts on is whatever region was right-clicked. `Popover` measures a
 * trigger element, so there is nothing for it to measure here.
 *
 * The rows are shared with `Menu` (`menuItems.tsx`): the same action reached two
 * ways should not be two sets of markup that drift into looking like two menus.
 *
 * **An empty item list yields to the browser.** A region that offers nothing in
 * context should give the operator back their own menu rather than swallowing the
 * gesture and showing an empty box.
 *
 * **It flips rather than clips.** Opened near the right or bottom edge the panel is
 * placed back inside the window, which is what every native context menu does and
 * what makes one opened on the last pane still fully readable.
 */
export function ContextMenu(props: ContextMenuProps): JSX.Element {
  const [at, setAt] = createSignal<{ x: number; y: number } | null>(null);
  let panel: HTMLDivElement | undefined;

  const close = (): void => {
    setAt(null);
  };

  const place = (x: number, y: number): { x: number; y: number } => {
    const width = panel?.offsetWidth || ASSUMED.width;
    const height = panel?.offsetHeight || ASSUMED.height;
    return {
      x: Math.max(
        EDGE_MARGIN,
        Math.min(x, window.innerWidth - width - EDGE_MARGIN),
      ),
      y: Math.max(
        EDGE_MARGIN,
        Math.min(y, window.innerHeight - height - EDGE_MARGIN),
      ),
    };
  };

  const onContextMenu = (e: MouseEvent): void => {
    if (props.items().length === 0) return;
    e.preventDefault();
    // Deepest region wins: a pane inside the panel offers its own actions, and the
    // panel behind it must not also answer the same gesture.
    e.stopPropagation();
    setAt({ x: e.clientX, y: e.clientY });
  };

  const onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === "Escape") close();
  };
  // On the window, because the menu is portalled and the pointer may never enter it.
  window.addEventListener("keydown", onKeyDown);
  onCleanup(() => window.removeEventListener("keydown", onKeyDown));

  return (
    <>
      <div class={props.class} onContextMenu={onContextMenu}>
        {props.children}
      </div>
      <Show when={at()}>
        {(point) => {
          const pos = (): { x: number; y: number } =>
            place(point().x, point().y);
          return (
            <Portal>
              {/* The backdrop catches a click anywhere else, including a second
                  right-click, which should move the menu rather than stack one. */}
              <div
                class="fixed inset-0 z-[60]"
                onClick={close}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setAt({ x: e.clientX, y: e.clientY });
                }}
              />
              <div
                ref={panel}
                class={cx(
                  "ody-rise fixed z-[61] min-w-40 rounded-panel bg-surface py-1 shadow-2",
                )}
                style={{ left: `${pos().x}px`, top: `${pos().y}px` }}
              >
                <MenuItemList items={props.items()} close={close} />
              </div>
            </Portal>
          );
        }}
      </Show>
    </>
  );
}
