import { For, Show, type Accessor, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { Icon, ListRow, Text, Tooltip, cx } from "~/ui";
import type { NavArea } from "../nav";
import { areaMeta, navMeta } from "./navMeta";

/** One area of the rail: a header that is always visible (the map), and the
 *  area's pages beneath it while the section is open.
 *
 *  The header is a link — clicking it goes to the area's first page, and the
 *  route opens the section — while the plus/minus toggle is a separate button
 *  that opens and closes the section without navigating, so an area can be
 *  peeked at without leaving the current page. A chevron was tried here first
 *  but beside a link it reads as "go to that page"; plus/minus is the
 *  registration-crosshair disclosure of §5 and can't be misread. The two are
 *  siblings, not nested: a button inside a button is invalid HTML (the same
 *  reason ListRow's `right` slot is a span, not a button).
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
    <div class="pb-1">
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
          <Icon name={props.open() ? "minus" : "plus"} size={16} />
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
                  right={navMeta(item)}
                  // Indented so the rows read as the header's contents.
                  // Selection is a raised fill (§10 States) — the old 2px left
                  // rule turned the rail into a column of bars.
                  class={cx(
                    "rounded-ctl pl-5",
                    isActive(item.href) && "bg-raised",
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
