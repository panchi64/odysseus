import { type JSX } from "solid-js";
import { FramedOverlay, Icon, Panel, Text } from "~/ui";
import { SectionList } from "./SectionList";
import { SettingsPane } from "./SettingsPane";
import { groupForSection } from "./sections";
import { useSettingsRoute } from "./useSettingsRoute";

const TITLE_ID = "settings-dialog-title";

/**
 * Everything the operator configures, in one overlay: every configuration
 * surface down the left, the picked one on the right.
 *
 * It replaced eighteen rail rows. The rail's job is the work — threads — and a
 * permanent list of every configuration surface made it the app's table of
 * contents instead. Configuration is something you go *to*, deliberately, and
 * then leave; an overlay says that where a nav row says the opposite.
 *
 * **It is mounted once, by the shell, and reads its own state from the URL.**
 * No parent holds an `open` signal, because the thing that opens it (the rail's
 * footer pin) and the thing that shows it are not near each other in the tree,
 * and threading a signal between them would make the shell the owner of state
 * the URL already carries. `?settings=<section>` is the whole contract.
 *
 * The pane's own title is **not** here: every section component already opens
 * with its own header, so the shell contributes a breadcrumb instead of a second
 * heading saying the same words an inch above the first.
 *
 * `FramedOverlay` renders its children only while open, so every resource behind
 * these sections is created on open and torn down on close — the app pays
 * nothing at boot for settings nobody opened.
 */
export function SettingsDialog(): JSX.Element {
  const route = useSettingsRoute();
  const crumb = (): string => {
    const group = groupForSection(route.section().id);
    return ["SETTINGS", group?.label, route.section().label.toUpperCase()]
      .filter(Boolean)
      .join(" · ");
  };

  return (
    <FramedOverlay
      open={route.open()}
      onClose={route.close}
      labelledBy={TITLE_ID}
      /* Wide enough for two columns and a form beside them; tall enough that a
         long section scrolls inside the pane rather than resizing the frame,
         which would re-run the marks' geometry on every content change. */
      class="h-[80vh] max-w-4xl"
    >
      {/* `Panel bare` — one glass layer, at the frame's own box. A card here
          would wrap a rounded, elevated box around the frame, so the frosted
          area would read as a pane the marks decorate rather than the pane they
          describe. */}
      <Panel bare flush fill class="h-full">
        <div class="flex h-full min-h-0">
          <SectionList active={route.section()} onSelect={route.select} />

          <div class="flex min-h-0 min-w-0 flex-1 flex-col">
            <header class="flex items-start justify-between gap-4 px-5 pt-4 pb-1">
              <span id={TITLE_ID} class="min-w-0 truncate">
                <Text variant="meta" tone="dim">
                  {crumb()}
                </Text>
              </span>
              <button
                type="button"
                onClick={route.close}
                aria-label="Close settings"
                class="text-dim transition-colors hover:text-bright"
              >
                <Icon name="close" size={16} />
              </button>
            </header>

            {/* The pane owns the scroll, not the dialog: the section list must
                stay put while a long section scrolls past it. */}
            <div class="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 pt-2 pb-5">
              <SettingsPane section={route.section()} />
            </div>
          </div>
        </div>
      </Panel>
    </FramedOverlay>
  );
}
