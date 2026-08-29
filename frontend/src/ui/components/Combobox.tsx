import { For, Show, createMemo, createSignal, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";
import { type IconName } from "../icons/registry";
import { Popover } from "./Popover";
import { ListGroupHeader } from "./ListGroupHeader";

export interface ComboboxOption {
  value: string;
  label: string;
}

export interface ComboboxGroup {
  label: string;
  options: ComboboxOption[];
}

export interface ComboboxProps {
  /** Options grouped under headings (e.g. one group per provider/endpoint). */
  groups: ComboboxGroup[];
  value?: string;
  onChange?: (value: string) => void;
  /** Trigger text when nothing is selected. */
  placeholder?: string;
  /** Search-field placeholder. */
  searchPlaceholder?: string;
  /** Hide the search field (short lists). Default: shown. */
  searchable?: boolean;
  /** Glyph inside the trigger (e.g. `cpu`). */
  leading?: IconName;
  /** Panel alignment relative to the trigger. Default left. */
  align?: "left" | "right";
  /** Message when discovery returned nothing. */
  emptyHint?: string;
  /** Drop the trigger's fill and its minimum width, so it reads as a line of text
   *  with a chevron rather than a control.
   *
   *  For a trigger that already sits on a raised surface — the composer's action row
   *  — where the default fill would be a fill on a fill (§7). The min-width goes with
   *  it because a bare trigger has no box whose edges need to stay put: it is sized
   *  by the model name it is showing.
   *
   *  The label drops to `dim` with the fill, for the same reason: with no box to
   *  separate it, a `bright` value reads as a heading over whatever sits beneath it.
   *  A bare trigger is a setting the operator glances at and rarely changes, not a
   *  thing to announce. */
  bare?: boolean;
  /** Fired when the option list opens — for a caller whose options are worth
   *  re-fetching at the moment they're about to be looked at. */
  onOpen?: () => void;
  "aria-label"?: string;
  class?: string;
}

/** Searchable dropdown with grouped options — a Select that scales to long
 *  lists. Native `<select>` can't host a filter field, so this composes the
 *  shared Popover shell with a search box and a grouped option list. */
export function Combobox(props: ComboboxProps): JSX.Element {
  const [query, setQuery] = createSignal("");

  const selectedLabel = createMemo(() => {
    for (const g of props.groups)
      for (const o of g.options) if (o.value === props.value) return o.label;
    return undefined;
  });

  const filtered = createMemo(() => {
    const q = query().trim().toLowerCase();
    return props.groups
      .map((g) => ({
        label: g.label,
        options: q
          ? g.options.filter((o) => o.label.toLowerCase().includes(q))
          : g.options,
      }))
      .filter((g) => g.options.length > 0);
  });

  const searchable = () => props.searchable !== false;

  return (
    <Popover
      class={props.class}
      align={props.align}
      onOpen={props.onOpen}
      panelClass="flex max-h-80 w-64 flex-col"
      trigger={({ open, setOpen }) => (
        <button
          type="button"
          aria-label={props["aria-label"]}
          aria-haspopup="listbox"
          aria-expanded={open()}
          onClick={() => {
            setQuery("");
            setOpen(!open());
          }}
          class={cx(
            "flex h-8 max-w-56 items-center gap-1.5 rounded-ctl transition-colors hover:text-bright",
            // A filled trigger's padding is inside a visible box, so it reads as the
            // control's shape. A bare one has no box, so the same padding just reads as
            // a gap — and then the real gap beside it lands on top, pushing whatever
            // follows visibly further away than the next item in the row. Narrower
            // padding keeps the bare trigger's edge close to its text, which is what
            // lets a uniform gap actually look uniform.
            props.bare ? "min-w-0 px-1" : "min-w-32 bg-raised px-2",
          )}
        >
          <Show when={props.leading}>
            <Icon name={props.leading!} size={12} class="shrink-0 text-dim" />
          </Show>
          <Text
            variant="label"
            tone={selectedLabel() && !props.bare ? "bright" : "dim"}
            class="min-w-0 flex-1 truncate text-left"
          >
            {selectedLabel() ?? props.placeholder ?? "Select"}
          </Text>
          <Icon name="chevron-down" size={12} class="shrink-0 text-dim" />
        </button>
      )}
      panel={({ close }) => {
        const pick = (value: string) => {
          props.onChange?.(value);
          close();
        };
        const onSearchKey = (e: KeyboardEvent) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const first = filtered()[0]?.options[0];
            if (first) pick(first.value);
          }
        };
        return (
          <>
            <Show when={searchable()}>
              <div class="shrink-0 p-1.5">
                <div class="relative">
                  <Icon
                    name="search"
                    size={14}
                    class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-dim"
                  />
                  <input
                    ref={(el) => queueMicrotask(() => el.focus())}
                    value={query()}
                    onInput={(e) => setQuery(e.currentTarget.value)}
                    onKeyDown={onSearchKey}
                    placeholder={props.searchPlaceholder ?? "Search…"}
                    class="h-7 w-full rounded-ctl bg-raised pl-8 pr-2 font-sans text-body text-bright placeholder:text-dim outline-none transition-colors"
                  />
                </div>
              </div>
            </Show>

            <div class="min-h-0 flex-1 overflow-y-auto py-1">
              <Show
                when={filtered().length > 0}
                fallback={
                  <div class="px-3 py-2">
                    <Text variant="micro" tone="dim">
                      {props.groups.length === 0
                        ? (props.emptyHint ?? "No options")
                        : "No matches"}
                    </Text>
                  </div>
                }
              >
                <For each={filtered()}>
                  {(group) => (
                    <div>
                      <ListGroupHeader label={group.label} />
                      <For each={group.options}>
                        {(opt) => (
                          <button
                            type="button"
                            role="option"
                            aria-selected={opt.value === props.value}
                            onClick={() => pick(opt.value)}
                            class={cx(
                              "flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-raised",
                              opt.value === props.value && "bg-raised",
                            )}
                          >
                            <Icon
                              name="check"
                              size={12}
                              class={cx(
                                "shrink-0",
                                opt.value === props.value
                                  ? "text-nominal"
                                  : "opacity-0",
                              )}
                            />
                            <Text
                              variant="body"
                              tone={
                                opt.value === props.value ? "bright" : "default"
                              }
                              class="min-w-0 truncate"
                            >
                              {opt.label}
                            </Text>
                          </button>
                        )}
                      </For>
                    </div>
                  )}
                </For>
              </Show>
            </div>
          </>
        );
      }}
    />
  );
}
