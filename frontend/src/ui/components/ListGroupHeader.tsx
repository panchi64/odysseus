import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";

export interface ListGroupHeaderProps {
  label: string;
  class?: string;
}

/** The dim micro heading that names a run of rows inside a list — a grouped
 *  option list, a palette section. Not a `Panel`: it sits *within* one scroll
 *  body between two runs of rows, so it carries no border or ground of its own. */
export function ListGroupHeader(props: ListGroupHeaderProps): JSX.Element {
  const [local] = splitProps(props, ["label", "class"]);
  return (
    <div class={cx("px-3 pb-0.5 pt-1.5", local.class)}>
      <Text variant="micro" tone="dim">
        {local.label}
      </Text>
    </div>
  );
}
