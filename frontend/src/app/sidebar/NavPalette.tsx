import {
  createEffect,
  createMemo,
  createSignal,
  For,
  Show,
  type JSX,
} from "solid-js";
import { useNavigate } from "@solidjs/router";
import { Input, ListRow, Modal, Text } from "~/ui";
import { registerKeymap } from "~/lib/keymap";
import { flattenNav, searchNav, type NavMatch } from "../nav";

const [open, setOpen] = createSignal(false);

/** Opened by the rail's search glyph as well as `mod+k`, so the palette isn't
 *  only reachable by a shortcut you have to already know about. */
export function openNavPalette(): void {
  setOpen(true);
}

/**
 * The fast jump. It spans all areas and matches descriptions as well as
 * labels, since a page is often known by what it does rather than what it's
 * called — a keystroke beats expanding a section and scanning its rows.
 *
 * It's an overlay rather than a field in the rail because a permanent input cost
 * a band of vertical space and a third tier of clickable rows for something used
 * occasionally — and because an overlay has room to show the description that
 * makes a match make sense.
 */
export function NavPalette(): JSX.Element {
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const [cursor, setCursor] = createSignal(0);
  let input: HTMLInputElement | undefined;

  registerKeymap(() => [{ combo: "mod+k", run: () => setOpen(true) }]);

  // With no query the palette lists everything — an empty overlay would make
  // opening it a wasted keystroke, and the full list doubles as a directory.
  const matches = createMemo<NavMatch[]>(() =>
    query().trim() ? searchNav(query()) : flattenNav(),
  );

  createEffect(() => {
    if (!open()) return;
    setQuery("");
    setCursor(0);
    // The dialog mounts in the same tick; focus once it exists.
    queueMicrotask(() => input?.focus());
  });

  // Keep the cursor on a row that still exists as the query narrows.
  createEffect(() => {
    const max = matches().length - 1;
    if (cursor() > max) setCursor(max < 0 ? 0 : max);
  });

  const close = () => setOpen(false);
  const goTo = (href: string) => {
    close();
    navigate(href);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const list = matches();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((i) => Math.min(i + 1, list.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const hit = list[cursor()];
      if (hit) goTo(hit.item.href);
    } else if (e.key === "Escape") {
      close();
    }
  };

  return (
    <Modal open={open()} onClose={close} padded={false} class="max-w-xl">
      <div class="border-b border-line p-2">
        <Input
          ref={input}
          value={query()}
          onInput={(e) => {
            setQuery(e.currentTarget.value);
            setCursor(0);
          }}
          onKeyDown={onKeyDown}
          leading="search"
          placeholder="GO TO…"
          aria-label="Search navigation"
        />
      </div>

      <div class="max-h-96 overflow-y-auto">
        <Show
          when={matches().length > 0}
          fallback={
            <div class="px-3 py-4">
              <Text variant="micro" tone="dim">
                NO MATCH
              </Text>
            </div>
          }
        >
          <For each={matches()}>
            {(m, i) => (
              <ListRow
                label={m.item.label}
                description={m.item.description}
                leading={m.item.icon}
                selected={i() === cursor()}
                onClick={() => goTo(m.item.href)}
                right={
                  <Show when={m.area}>
                    {(area) => (
                      <Text variant="micro" tone="dim">
                        {area().label}
                      </Text>
                    )}
                  </Show>
                }
              />
            )}
          </For>
        </Show>
      </div>
    </Modal>
  );
}
