import { createSignal, For, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { Button, Icon, ListRow, Text, Tooltip, cx } from "~/ui";
import { useSession } from "~/lib/stores/session";
import { useSettingsRoute } from "~/app/settings-dialog";
import { RecentsRail } from "~/features/chat/components/RecentsRail";
import { AREAS, areaForPath, TOP_PINS, type NavItem } from "../nav";
import { AreaSection } from "./AreaSection";
import { NavPalette, openNavPalette } from "./NavPalette";
import { navMeta } from "./navMeta";
import { ProjectSwitcher } from "./ProjectSwitcher";

/** A destination kept outside the one area. */
function PinRow(props: { item: NavItem; active: boolean }): JSX.Element {
  return (
    <Tooltip
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

/** The rail: the places you work, then the threads you work in.
 *
 *  It used to list nineteen surfaces across six areas — the app's table of
 *  contents, permanently occupying the space beside the work. Everything that
 *  was configuration now lives in the settings dialog, so what is left is the
 *  handful of surfaces that are genuinely destinations, and beneath them the
 *  conversation list, which is the rail's actual body.
 *
 *  COMMS is the one group left, and it sits in the footer rather than above the
 *  threads: mail and a calendar are things you check, not the thing you are
 *  doing. It is collapsed unless the route is inside it, so at rest the rail
 *  reads as chat with two rows underneath. */
export function Sidebar(): JSX.Element {
  const location = useLocation();
  const session = useSession();
  const settings = useSettingsRoute();
  const activeArea = () => areaForPath(location.pathname);
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  const comms = AREAS[0];
  // Open when the route is inside COMMS, and otherwise whatever the operator
  // last toggled it to. Derived-then-overridden, like the area sections were —
  // arriving in the area always shows its pages.
  const [commsOverride, setCommsOverride] = createSignal<boolean>();
  const commsOpen = (): boolean =>
    commsOverride() ?? activeArea()?.id === comms.id;

  return (
    <nav class="flex h-full min-h-0 flex-col bg-surface">
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
          <Tooltip side="right" label="Go to… (⌘K)">
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

      <ProjectSwitcher />

      {/* The threads. Mounted on every route, not only `/chat` — the rail used
          to host this through a route-matched slot, which made the conversation
          list disappear the moment you looked at anything else. */}
      <RecentsRail />

      <div class="sticky bottom-0 mt-2 bg-surface pt-2">
        <AreaSection
          area={comms}
          active={activeArea()?.id === comms.id}
          open={commsOpen}
          onToggle={() => setCommsOverride(!commsOpen())}
        />

        {/* Settings opens the dialog rather than navigating, so it takes an
            `onClick` and not an `href`: a row that looks like every other
            destination but changes no route would be a lie about what clicking
            it does.

            No indicator rolls up to it, and none needs to. The area switcher's
            rollup existed because an area's activity went dark the moment you
            navigated out of it — but the only two live signals are a chat run
            (parked approval or streaming), which the Chat pin above carries and
            which is now permanent, and COMMS, whose own header still shows it.
            There is nothing left that could go dark. */}
        <Tooltip
          delay={1000}
          side="right"
          label="Preferences, connections, and the state of the machine"
          class="block w-full"
        >
          <ListRow
            label="Settings"
            leading="settings"
            onClick={() => settings.show()}
            selected={settings.open()}
            class={cx("rounded-ctl", settings.open() && "bg-raised")}
          />
        </Tooltip>

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
