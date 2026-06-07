import { Show, splitProps, type JSX } from "solid-js";
import { Dynamic } from "solid-js/web";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon, type IconProps } from "../primitives/Icon";

export interface ListRowProps {
  /** Primary label, left-aligned. */
  label: string;
  /** Leading icon. */
  leading?: IconProps["name"];
  /** Right-aligned content: status flag, meta, icon. */
  right?: JSX.Element;
  selected?: boolean;
  locked?: boolean;
  href?: string;
  onClick?: () => void;
  /** Drop the bottom hairline (e.g. the last row in a group). */
  flush?: boolean;
  class?: string;
}

/** Single-line row: label left, optional status/icon right, hairline below
 *  (§6.7). Locked rows are dim with a lock glyph. */
export function ListRow(props: ListRowProps): JSX.Element {
  const [local] = splitProps(props, [
    "label",
    "leading",
    "right",
    "selected",
    "locked",
    "href",
    "onClick",
    "flush",
    "class",
  ]);
  const interactive = () => !local.locked && (local.href || local.onClick);
  const tag = () =>
    local.locked ? "div" : local.href ? "a" : local.onClick ? "button" : "div";
  return (
    <Dynamic
      component={tag()}
      href={!local.locked ? local.href : undefined}
      onClick={!local.locked ? local.onClick : undefined}
      aria-disabled={local.locked || undefined}
      class={cx(
        "flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors",
        !local.flush && "border-b border-line",
        local.selected && "bg-raised",
        interactive() && "hover:bg-raised",
        local.locked && "cursor-not-allowed",
        local.class,
      )}
    >
      <span class="flex min-w-0 items-center gap-2">
        <Show when={local.leading}>
          <Icon
            name={local.leading!}
            class={local.locked ? "text-dim" : "text-dim"}
          />
        </Show>
        <Text
          variant="label"
          tone={local.locked ? "dim" : local.selected ? "bright" : "default"}
          class="truncate"
        >
          {local.label}
        </Text>
      </span>
      <span class="flex shrink-0 items-center gap-2">
        <Show when={local.right}>{local.right}</Show>
        <Show when={local.locked}>
          <Icon name="lock" size={12} class="text-dim" />
        </Show>
      </span>
    </Dynamic>
  );
}
