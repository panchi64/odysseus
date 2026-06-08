import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";
import { type IconName } from "../icons/registry";

export interface ChipProps {
  children: JSX.Element;
  /** When set, the chip is a button that fires this on click (example queries,
   *  suggestion pills, removable tags). Omit for a static token. */
  onClick?: () => void;
  leading?: IconName;
  class?: string;
}

const base =
  "inline-flex items-center gap-1 border border-line px-2 py-1 text-micro text-dim";

/** Compact bordered token for short labels / selectable suggestions. Static by
 *  default; pass `onClick` to make it an interactive button. Centralizes the
 *  hand-rolled "bordered micro pill" that otherwise gets re-inlined per screen. */
export function Chip(props: ChipProps): JSX.Element {
  const [local] = splitProps(props, [
    "children",
    "onClick",
    "leading",
    "class",
  ]);
  const body = (
    <>
      <Show when={local.leading}>
        <Icon name={local.leading!} size={12} />
      </Show>
      {local.children}
    </>
  );
  return (
    <Show
      when={local.onClick}
      fallback={<span class={cx(base, local.class)}>{body}</span>}
    >
      <button
        type="button"
        onClick={() => local.onClick!()}
        class={cx(
          base,
          "text-left transition-colors hover:border-bright hover:text-bright",
          local.class,
        )}
      >
        {body}
      </button>
    </Show>
  );
}
