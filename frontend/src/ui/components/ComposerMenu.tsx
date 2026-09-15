import { For, Show, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { ListGroupHeader } from "./ListGroupHeader";
import { FloatingPanel } from "./Popover";
import { type Rect } from "./popoverPlacement";

export interface ComposerMenuItem {
  /** Unique across the whole menu — it is the row's DOM id, which is what
   *  `aria-activedescendant` on the field points at. */
  id: string;
  /** What picking this inserts, and what the row leads with. */
  label: string;
  /** One line under the label. Optional — a file row is its own description. */
  detail?: string;
  /** Dim trailing note: an argument hint, or which source outranks this name. */
  meta?: string;
}

export interface ComposerMenuGroup {
  id: string;
  /** Heading text. Comes from the backend for the command menu, so a source added
   *  server-side is never a blank section in a client that has not shipped yet. */
  label: string;
  items: ComposerMenuItem[];
}

export interface ComposerMenuProps {
  open: boolean;
  groups: ComposerMenuGroup[];
  /** The field's own rect, re-read each pass. The menu docks to the field rather than
   *  to the caret — see the component note. */
  anchor: () => Rect | null;
  /** Id of the row the keyboard is on. The caller owns it, because the caller owns the
   *  keys: focus never leaves the field, so the arrows arrive there. */
  activeId: string | null;
  onPick: (item: ComposerMenuItem) => void;
  /** Hover moves the selection, so mouse and keyboard share one cursor rather than
   *  lighting two different rows at once. */
  onActivate?: (item: ComposerMenuItem) => void;
  /** Shown when the trigger matched nothing. */
  emptyHint?: string;
}

/**
 * The composer's `/` and `@` menu: a grouped, keyboard-driven list docked to the field.
 *
 * **It is render-only, and that is the whole design.** Focus stays in the textarea the
 * whole time the menu is up, so the panel can never receive a keystroke — it is portalled
 * to `document.body` (`FloatingPanel`), which puts it outside the field's subtree, so
 * nothing typed there bubbles here. Arrow keys, Enter, Tab and Escape are handled on the
 * *field*, and the menu is told which row is active through `activeId`. A container-level
 * keydown of the kind `NavPalette` uses would simply never fire, because the palette owns
 * its own input and this owns nothing.
 *
 * **It docks to the field, not to the caret.** A caret-anchored menu needs the mirror-div
 * measurement trick — a hidden copy of the textarea, restyled and re-measured on every
 * keystroke — which is fiddly, untestable without a DOM, and buys nothing on a field that
 * is one to six rows tall. `block` floors the panel at the field's width so it reads as
 * an extension of it.
 *
 * Rows are `option`s under a `listbox`, with the field carrying `aria-activedescendant` —
 * the same arrangement the palette uses, and the reason the ids have to be unique across
 * groups rather than per group.
 */
export function ComposerMenu(props: ComposerMenuProps): JSX.Element {
  const empty = () => props.groups.every((group) => group.items.length === 0);
  return (
    <FloatingPanel
      open={() => props.open}
      // Dismissal belongs to the field: the menu lives off what is typed in it, so it
      // closes when the token does. Nothing to do here.
      onClose={() => {}}
      passive
      block
      anchor={props.anchor}
      panelClass="max-h-72 overflow-y-auto scrollbar-thin py-1"
      panel={() => (
        // The id the field's `aria-controls` points at. Fixed rather than generated:
        // only one composer menu is ever open, because only one field has focus.
        <div id="composer-menu" role="listbox">
          <Show
            when={!empty()}
            fallback={
              <div class="px-3 py-2">
                <Text variant="micro" tone="dim">
                  {props.emptyHint ?? "No matches"}
                </Text>
              </div>
            }
          >
            <For each={props.groups.filter((group) => group.items.length > 0)}>
              {(group) => (
                <div>
                  <ListGroupHeader label={group.label} />
                  <For each={group.items}>
                    {(item) => (
                      <div
                        id={item.id}
                        role="option"
                        aria-selected={item.id === props.activeId}
                        // `onMouseDown` with the default prevented, never `onClick`:
                        // a click would blur the textarea first, and a blur is what
                        // dismisses the menu — so the row would be gone before its own
                        // handler ran.
                        onMouseDown={(e) => {
                          e.preventDefault();
                          props.onPick(item);
                        }}
                        onMouseEnter={() => props.onActivate?.(item)}
                        class={cx(
                          "flex cursor-pointer items-baseline gap-2 px-3 py-1.5",
                          item.id === props.activeId && "bg-raised",
                        )}
                      >
                        <Text
                          variant="body"
                          tone={
                            item.id === props.activeId ? "bright" : "default"
                          }
                          class="shrink-0"
                        >
                          {item.label}
                        </Text>
                        <Show when={item.detail}>
                          <Text
                            variant="meta"
                            tone="dim"
                            class="min-w-0 truncate"
                          >
                            {item.detail}
                          </Text>
                        </Show>
                        <Show when={item.meta}>
                          <Text
                            variant="micro"
                            tone="dim"
                            class="ml-auto shrink-0"
                          >
                            {item.meta}
                          </Text>
                        </Show>
                      </div>
                    )}
                  </For>
                </div>
              )}
            </For>
          </Show>
        </div>
      )}
    />
  );
}
