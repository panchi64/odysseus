import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { Icon, Input, ListRow, Text } from "~/ui";
import { registerKeymap } from "~/lib/keymap";
import { searchNav } from "../nav";

/** The escape hatch. One area is visible at a time, so search is what keeps
 *  every other surface one keystroke away: it spans all areas, matches
 *  descriptions as well as labels, and `mod+k` focuses it from anywhere. */
export function NavSearch(): JSX.Element {
  const navigate = useNavigate();
  const [query, setQuery] = createSignal("");
  const matches = createMemo(() => searchNav(query()));
  let input: HTMLInputElement | undefined;

  registerKeymap(() => [
    {
      combo: "mod+k",
      run: () => {
        input?.focus();
        input?.select();
      },
    },
  ]);

  const goTo = (href: string) => {
    setQuery("");
    input?.blur();
    navigate(href);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      const m = matches();
      if (m.length) goTo(m[0].item.href);
    } else if (e.key === "Escape") {
      setQuery("");
    }
  };

  return (
    <div class="relative border-b border-line p-2">
      <Icon
        name="search"
        size={14}
        class="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-dim"
      />
      <Input
        ref={input}
        value={query()}
        onInput={(e) => setQuery(e.currentTarget.value)}
        onKeyDown={onKeyDown}
        placeholder="SEARCH"
        aria-label="Search navigation"
        class="pl-7"
      />

      <Show when={query().trim().length > 0}>
        <div class="absolute inset-x-2 top-full z-40 max-h-80 overflow-y-auto border border-line bg-surface">
          <Show
            when={matches().length > 0}
            fallback={
              <div class="px-3 py-2">
                <Text variant="micro" tone="dim">
                  NO MATCH
                </Text>
              </div>
            }
          >
            <For each={matches()}>
              {(m) => (
                <ListRow
                  label={m.item.label}
                  leading={m.item.icon}
                  onClick={() => goTo(m.item.href)}
                  right={
                    <Text variant="micro" tone="dim">
                      {m.area.label}
                    </Text>
                  }
                />
              )}
            </For>
          </Show>
        </div>
      </Show>
    </div>
  );
}
