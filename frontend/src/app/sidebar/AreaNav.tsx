import { createEffect, createSignal, For, Show, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { AREAS, type NavArea } from "../nav";
import { AreaSection } from "./AreaSection";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { railSlotFor } from "./railSlots";

/** The rail body: whatever live panel the current route contributes (RECENTS
 *  on /chat), then every area as a section.
 *
 *  All six headers are always visible — the map of the app at a glance — and
 *  which sections are open is derived, never persisted: the area the route
 *  sits in opens by default, and the operator's plus/minus toggle layers on
 *  top for the session. Toggles clear when the route lands in that area, because
 *  arriving always shows the area's pages. */
export function AreaNav(props: { active: NavArea | undefined }): JSX.Element {
  const location = useLocation();
  const slot = () => railSlotFor(location.pathname);

  const [overrides, setOverrides] = createSignal<Record<string, boolean>>({});
  createEffect(() => {
    const id = props.active?.id;
    if (!id) return;
    setOverrides((o) => {
      if (!(id in o)) return o;
      const { [id]: _dropped, ...rest } = o;
      return rest;
    });
  });

  const isOpen = (area: NavArea): boolean =>
    overrides()[area.id] ?? props.active?.id === area.id;
  const toggle = (area: NavArea): void => {
    setOverrides((o) => ({ ...o, [area.id]: !isOpen(area) }));
  };

  return (
    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <ProjectSwitcher />
      <Show when={slot()}>
        {(match) => <div class="min-h-0">{match().render()}</div>}
      </Show>
      <For each={AREAS}>
        {(area) => (
          <AreaSection
            area={area}
            active={props.active?.id === area.id}
            open={() => isOpen(area)}
            onToggle={() => toggle(area)}
          />
        )}
      </For>
    </div>
  );
}
