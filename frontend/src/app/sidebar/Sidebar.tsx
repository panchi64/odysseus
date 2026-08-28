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
        right={navMeta(props.item)}
        // Selection is a raised fill on a smoothed corner (§10 States), not the
        // old 2px left rule — a rail of vertical bars was reading as chrome, and
        // the fill says "you are here" without adding a line to the page.
        class={cx("rounded-ctl", props.active && "bg-raised")}
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
        <div class="flex items-center justify-between gap-2 pr-2">
          <a
            href="/"
            class="mx-1 flex min-w-0 flex-1 flex-col gap-1 rounded-ctl px-2 py-3 transition-colors hover:bg-raised"
          >
            {/* A wordmark is neither the interface talking nor the machine
                reporting — it is a name. Sans with the display tracking reads
                as a logotype; the old uppercase read as one more HUD label. */}
            <Text variant="readout" tone="bright" class="tracking-tight">
              Odysseus
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

        <div class="pb-2">
          <For each={TOP_PINS}>
            {(item) => <PinRow item={item} active={isActive(item.href)} />}
          </For>
        </div>
      </div>

      <AreaNav active={activeArea()} />

      <div class="sticky bottom-0 mt-2 bg-surface pt-2">
        <For each={FOOTER_PINS}>
          {(item) => <PinRow item={item} active={isActive(item.href)} />}
        </For>
        <div class="flex items-center justify-between gap-2 px-3 py-3">
          <span class="flex items-center gap-2">
            <Icon name="user" size={16} class="text-dim" />
            <Text variant="label" tone="dim">
              Operator
            </Text>
          </span>
          <Button
            variant="ghost"
            size="sm"
            leading="lock"
            onClick={() => void session.lock()}
          >
            Lock
          </Button>
        </div>
      </div>

      <NavPalette />
    </nav>
  );
}
