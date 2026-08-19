import { For, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { Button, Icon, ListRow, Text, Tooltip, cx } from "~/ui";
import { useSession } from "~/lib/stores/session";
import {
  anchorItem,
  areaForPath,
  FOOTER_ANCHORS,
  TOP_ANCHORS,
  type NavItem,
} from "../nav";
import { AreaNav } from "./AreaNav";
import { AreaSwitcher } from "./AreaSwitcher";
import { NavSearch } from "./NavSearch";
import { navMeta } from "./navMeta";

/** An area's entry point, kept outside the switcher. */
function AnchorRow(props: { item: NavItem; active: boolean }): JSX.Element {
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

/** Primary navigation rail, in two tiers: a switcher naming the area you're in,
 *  and that area's pages below it. Which area is active is derived from the
 *  route — nothing here stores it. */
export function Sidebar(): JSX.Element {
  const location = useLocation();
  const session = useSession();
  const activeArea = () => areaForPath(location.pathname);
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);
  // Only the top anchors are dropped from the body list — they sit immediately
  // above it, so repeating them would read as a duplicate. A footer anchor is a
  // shortcut *into* its area from anywhere, so its row still belongs in the list
  // once you're there (otherwise SYSTEM would silently lose "Appearance").
  const pinnedHrefs = () => TOP_ANCHORS.map((a) => anchorItem(a).href);

  return (
    <nav class="flex min-h-full flex-col bg-surface">
      <div class="sticky top-0 z-30 bg-surface">
        <a
          href="/"
          class="flex flex-col gap-0.5 border-b border-line px-3 py-3 transition-colors hover:bg-raised"
        >
          <Text variant="readout" tone="bright" class="font-display">
            ODYSSEUS
          </Text>
          <Text variant="micro" tone="dim">
            ODY-WORKSPACE-02.1
          </Text>
        </a>

        <NavSearch />

        <div class="border-b border-line p-2">
          <AreaSwitcher active={activeArea()} />
        </div>

        <For each={TOP_ANCHORS}>
          {(area) => {
            const item = anchorItem(area);
            return <AnchorRow item={item} active={isActive(item.href)} />;
          }}
        </For>
      </div>

      <AreaNav active={activeArea()} pinned={pinnedHrefs()} />

      <div class="sticky bottom-0 border-t border-line bg-surface">
        <For each={FOOTER_ANCHORS}>
          {(area) => {
            const item = anchorItem(area);
            return <AnchorRow item={item} active={isActive(item.href)} />;
          }}
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
    </nav>
  );
}
