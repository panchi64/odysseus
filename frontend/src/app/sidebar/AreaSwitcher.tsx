import { For, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { Icon, ListRow, Popover, Text, cx } from "~/ui";
import { AREAS, type NavArea } from "../nav";
import { areaMeta } from "./navMeta";

/** The rail's first tier: which area the panel below is showing. The trigger
 *  reports the derived active area and holds no state of its own. `undefined` is
 *  a real state, not a bug — the launchpad belongs to no area. */
export function AreaSwitcher(props: {
  active: NavArea | undefined;
}): JSX.Element {
  const navigate = useNavigate();

  return (
    <Popover
      block
      panelClass="max-h-[70vh] overflow-y-auto"
      trigger={({ open, setOpen }) => (
        <button
          type="button"
          onClick={() => setOpen(!open())}
          aria-expanded={open()}
          aria-haspopup="menu"
          aria-label="Switch area"
          class={cx(
            "flex w-full items-center justify-between gap-2 border border-line px-3 py-2 text-left transition-colors hover:bg-raised",
            open() && "bg-raised",
          )}
        >
          <span class="flex min-w-0 items-center gap-2">
            <Icon
              name={props.active?.icon ?? "grid"}
              class={props.active ? "text-bright" : "text-dim"}
            />
            <Text
              variant="label"
              tone={props.active ? "bright" : "dim"}
              class="truncate"
            >
              {props.active?.label ?? "WORKSPACE"}
            </Text>
          </span>
          <span class="flex shrink-0 items-center gap-1.5">
            <Show when={props.active}>{(a) => areaMeta(a())}</Show>
            <Icon
              name={open() ? "chevron-up" : "chevron-down"}
              size={12}
              class="text-dim"
            />
          </span>
        </button>
      )}
      panel={({ close }) => (
        <For each={AREAS}>
          {(area) => (
            <ListRow
              label={area.label}
              description={area.description}
              leading={area.icon}
              selected={area.id === props.active?.id}
              right={areaMeta(area)}
              onClick={() => {
                close();
                navigate(area.items[0].href);
              }}
            />
          )}
        </For>
      )}
    />
  );
}
