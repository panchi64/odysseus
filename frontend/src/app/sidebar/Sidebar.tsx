import { For, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { Button, Icon, ListRow, Text, Tooltip, cx } from "~/ui";
import { useSession } from "~/lib/stores/session";
import { areaForPath, FOOTER_PINS, TOP_PINS, type NavItem } from "../nav";
import { AreaNav } from "./AreaNav";
import { NavPalette, openNavPalette } from "./NavPalette";
import { navMeta } from "./navMeta";

/** A destination kept outside the switcher. */
function PinRow(props: { item: NavItem; active: boolean }): JSX.Element {
  return (
    <Tooltip
      float
      delay={1000}
      side="right"
      label={props.item.description}
      class="block w-full"
    >
      <ListRow
        label={props.item.label}
        leading={props.item.icon}
        href={props.item.href}
        selected={props.active}
        flush
        right={navMeta(props.item)}
        // §6 States — selection is marked by a 2px emphasis rule, not by color
        // alone.
        class={cx(
          "border-l-2",
          props.active ? "border-bright" : "border-transparent",
        )}
      />
    </Tooltip>
  );
}

/** Primary navigation rail: pinned rows, then every area as a collapsible
 *  section. Which section the route sits in is derived from the path — nothing
 *  here stores it.
 *
 *  Pins sit *outside* the sections — above the list, in the footer — so a
 *  permanent row never reads as a page of whichever area happens to be open. */
export function Sidebar(): JSX.Element {
  const location = useLocation();
  const session = useSession();
  const activeArea = () => areaForPath(location.pathname);
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  return (
    <nav class="flex min-h-full flex-col bg-surface">
      <div class="sticky top-0 z-30 bg-surface">
        <div class="flex items-center justify-between gap-2 border-b border-line pr-2">
          <a
            href="/"
            class="flex min-w-0 flex-1 flex-col gap-0.5 px-3 py-3 transition-colors hover:bg-raised"
          >
            <Text variant="readout" tone="bright" class="font-display">
              ODYSSEUS
            </Text>
            <Text variant="micro" tone="dim">
              ODY-WORKSPACE-02.1
            </Text>
          </a>
          <Tooltip float side="right" label="Go to… (⌘K)">
            <Button
              variant="ghost"
              size="sm"
              leading="search"
              aria-label="Go to page"
              onClick={openNavPalette}
            />
          </Tooltip>
        </div>

        <div class="border-b border-line">
          <For each={TOP_PINS}>
            {(item) => <PinRow item={item} active={isActive(item.href)} />}
          </For>
        </div>
      </div>

      <AreaNav active={activeArea()} />

      <div class="sticky bottom-0 border-t border-line bg-surface">
        <For each={FOOTER_PINS}>
          {(item) => <PinRow item={item} active={isActive(item.href)} />}
        </For>
        <div class="flex items-center justify-between gap-2 px-3 py-3">
          <span class="flex items-center gap-2">
            <Icon name="user" size={14} class="text-dim" />
            <Text variant="label" tone="dim">
              OPERATOR
            </Text>
          </span>
          <Button
            variant="ghost"
            size="sm"
            leading="lock"
            onClick={() => void session.lock()}
          >
            LOCK
          </Button>
        </div>
      </div>

      <NavPalette />
    </nav>
  );
}
