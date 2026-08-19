import { For, Show, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { EmptyState, ListRow, Tooltip, cx } from "~/ui";
import { AREAS, type NavArea, type NavItem } from "../nav";
import { navMeta } from "./navMeta";
import { railSlotFor } from "./railSlots";

/** The rail's second tier: the pages inside the active area, plus whatever live
 *  panel the current route contributes. With no active area this is the area
 *  list itself, so `/` reads as a directory of the workspace. */
export function AreaNav(props: {
  active: NavArea | undefined;
  /** Hrefs already pinned above — not repeated here. */
  pinned: string[];
}): JSX.Element {
  const location = useLocation();
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  const rows = (): NavItem[] =>
    props.active
      ? props.active.items.filter((i) => !props.pinned.includes(i.href))
      : [];

  return (
    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <Show
        when={props.active}
        fallback={
          <div class="py-2">
            <For each={AREAS}>
              {(area) => (
                <ListRow
                  label={area.label}
                  description={area.description}
                  leading={area.icon}
                  href={area.items[0].href}
                />
              )}
            </For>
          </div>
        }
      >
        <div class="py-2">
          <For each={rows()}>
            {(item) => (
              <Tooltip
                float
                delay={1000}
                side="right"
                label={item.description}
                class="block w-full"
              >
                <ListRow
                  label={item.label}
                  leading={item.icon}
                  href={item.href}
                  selected={isActive(item.href)}
                  flush
                  right={navMeta(item)}
                  // §6 States — selection is marked by a 2px emphasis rule, not
                  // by color alone.
                  class={cx(
                    "border-l-2",
                    isActive(item.href)
                      ? "border-bright"
                      : "border-transparent",
                  )}
                />
              </Tooltip>
            )}
          </For>
          <Show when={rows().length === 0 && !railSlotFor(location.pathname)}>
            <EmptyState message="NO PAGES" />
          </Show>
        </div>
      </Show>

      <Show when={railSlotFor(location.pathname)}>
        {(slot) => <div class="min-h-0 flex-1">{slot().render()}</div>}
      </Show>
    </div>
  );
}
