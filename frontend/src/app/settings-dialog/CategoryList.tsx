import { For, type JSX } from "solid-js";
import { ListRow, Text, Tooltip, cx } from "~/ui";
import { SETTINGS_CATEGORIES, type SettingsCategory } from "./categories";

/**
 * The dialog's left column: every category, always all of them.
 *
 * Nothing collapses and nothing is hidden behind a switcher — six rows is a list
 * you read rather than navigate, and the rail this replaced proved that a
 * hierarchy over a list this size costs more than it saves.
 *
 * Selection is the same raised fill the rail uses (§10 States), not a rule down
 * the side: this column already sits beside the pane, and a second vertical line
 * a few pixels from that edge reads as a mistake.
 */
export function CategoryList(props: {
  active: SettingsCategory;
  onSelect: (id: string) => void;
}): JSX.Element {
  return (
    <nav
      class="scrollbar-thin flex w-44 shrink-0 flex-col gap-0.5 overflow-y-auto p-2"
      aria-label="Settings categories"
    >
      <div class="px-2 pt-1 pb-2">
        <Text variant="meta" tone="dim">
          Settings
        </Text>
      </div>
      <For each={SETTINGS_CATEGORIES}>
        {(category) => (
          <Tooltip
            delay={1000}
            side="right"
            label={category.description}
            class="block w-full"
          >
            <ListRow
              label={category.label}
              leading={category.icon}
              selected={category.id === props.active.id}
              onClick={() => props.onSelect(category.id)}
              class={cx(
                "rounded-ctl",
                category.id === props.active.id && "bg-raised",
              )}
            />
          </Tooltip>
        )}
      </For>
    </nav>
  );
}
