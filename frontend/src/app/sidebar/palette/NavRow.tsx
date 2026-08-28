import { Show, type JSX } from "solid-js";
import { ListRow, Text } from "~/ui";
import type { NavMatch } from "~/app/nav";

export interface NavRowProps {
  match: NavMatch;
  /** DOM id, so the palette's field can point here with `aria-activedescendant`. */
  id: string;
  selected: boolean;
  onActivate: () => void;
}

/** One page row in the palette — the behaviour the palette has always had:
 *  activating it navigates and closes. It carries its description, because a
 *  page is often known by what it does rather than what it's called, and its
 *  area on the right, because a label alone doesn't say where it lives. */
export function NavRow(props: NavRowProps): JSX.Element {
  return (
    <ListRow
      option
      id={props.id}
      selected={props.selected}
      label={props.match.item.label}
      description={props.match.item.description}
      leading={props.match.item.icon}
      onClick={props.onActivate}
      right={
        <Show when={props.match.area}>
          {(area) => (
            <Text variant="micro" tone="dim">
              {area().label}
            </Text>
          )}
        </Show>
      }
    />
  );
}
