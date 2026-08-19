import { For, Show, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { ListRow, Tooltip, cx } from "~/ui";
import { AREAS, type NavArea } from "../nav";
import { navMeta } from "./navMeta";
import { railSlotFor } from "./railSlots";

/** The rail's second tier: the pages inside the active area, indented under the
 *  switcher that names it, plus whatever live panel the current route
 *  contributes.
 *
 *  With no active area this is a pinned page (its rail slot is the whole body —
 *  an area list would be answering a question nobody asked) or the launchpad, in
 *  which case the areas themselves are the list. */
export function AreaNav(props: { active: NavArea | undefined }): JSX.Element {
  const location = useLocation();
  const slot = () => railSlotFor(location.pathname);
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  return (
    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <Show
        when={props.active}
        fallback={
          <Show when={!slot()}>
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
          </Show>
        }
      >
        {(area) => (
          <div class="py-2">
            <For each={area().items}>
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
                    // Indented so the rows read as the switcher's contents; §6
                    // States — selection is a 2px emphasis rule, not color alone.
                    class={cx(
                      "border-l-2 pl-5",
                      isActive(item.href)
                        ? "border-bright"
                        : "border-transparent",
                    )}
                  />
                </Tooltip>
              )}
            </For>
          </div>
        )}
      </Show>

      <Show when={slot()}>
        {(match) => <div class="min-h-0 flex-1">{match().render()}</div>}
      </Show>
    </div>
  );
}
