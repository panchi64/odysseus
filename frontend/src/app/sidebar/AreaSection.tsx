import { For, Show, type Accessor, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { Icon, ListRow, Text, Tooltip, cx } from "~/ui";
import type { NavArea } from "../nav";
import { areaMeta, navMeta } from "./navMeta";

/** One area of the rail: a header that is always visible (the map), and the
 *  area's pages beneath it while the section is open.
 *
 *  The header is a link — clicking it goes to the area's first page, and the
 *  route opens the section — while the chevron is a separate button that
 *  toggles open state without navigating, so an area can be peeked at without
 *  leaving the current page. The two are siblings, not nested: a button inside
 *  a button is invalid HTML (the same reason ListRow's `right` slot is a span,
 *  not a button).
 *
 *  `active` (the route sits in this area) and `open` are different: a peeked
 *  section is open but not active, and the active section is the one whose
 *  header and icon read bright. */
export function AreaSection(props: {
  area: NavArea;
  active: boolean;
  open: Accessor<boolean>;
  onToggle: () => void;
}): JSX.Element {
  const location = useLocation();
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  return (
    <div class="border-b border-line">
      <div class="flex items-center">
        <a
          href={props.area.items[0].href}
          class="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 transition-colors hover:bg-raised"
        >
          <Icon
            name={props.area.icon}
            class={props.active ? "text-bright" : "text-dim"}
          />
          <Text
            variant="label"
            tone={props.active ? "bright" : "default"}
            class="truncate"
          >
            {props.area.label}
          </Text>
          {areaMeta(props.area)}
        </a>
        <button
          type="button"
          aria-expanded={props.open()}
          aria-label={`${props.open() ? "Collapse" : "Expand"} ${props.area.label}`}
          onClick={props.onToggle}
          class="flex size-7 shrink-0 items-center justify-center text-dim transition-colors hover:bg-raised hover:text-text"
        >
          <Icon
            name={props.open() ? "chevron-down" : "chevron-right"}
            size={12}
          />
        </button>
      </div>
      <Show when={props.open()}>
        <div class="pb-1">
          <For each={props.area.items}>
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
                  // Indented so the rows read as the header's contents; §6
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
      </Show>
    </div>
  );
}
