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
  /** Render a leading selection checkbox (driven by `selected`). The row's
   *  `onClick` should toggle selection. Replaces the `leading` icon. */
  selectable?: boolean;
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
    "selectable",
    "locked",
    "href",
    "onClick",
    "flush",
    "class",
  ]);
  const interactive = () => !local.locked && (local.href || local.onClick);
  // Selectable rows stay a <div> (with button semantics) so their `right` slot
  // can hold real interactive content — a Menu, copy button — without nesting a
  // <button> inside a <button> (invalid HTML / hydration warnings).
  const tag = () =>
    local.locked || local.selectable
      ? "div"
      : local.href
        ? "a"
        : local.onClick
          ? "button"
          : "div";
  return (
    <Dynamic
      component={tag()}
      href={!local.locked ? local.href : undefined}
      onClick={!local.locked ? local.onClick : undefined}
      role={local.selectable ? "button" : undefined}
      aria-pressed={local.selectable ? local.selected || false : undefined}
      tabindex={local.selectable && !local.locked ? 0 : undefined}
      onKeyDown={
        local.selectable && !local.locked
          ? (e: KeyboardEvent & { currentTarget: HTMLElement }) => {
              // Only the row itself toggles — keys aimed at a nested control
              // in the `right` slot (Menu, copy button) must not double-fire.
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                local.onClick?.();
              }
            }
          : undefined
      }
      aria-disabled={local.locked || undefined}
      class={cx(
        "flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors",
        !local.flush && "border-b border-line",
        local.selected && "bg-raised",
        interactive() && "hover:bg-raised",
        local.selectable && !local.locked && "cursor-pointer",
        local.locked && "cursor-not-allowed",
        local.class,
      )}
    >
      <span class="flex min-w-0 items-center gap-2">
        <Show when={local.selectable}>
          <span
            class={cx(
              "flex size-4 shrink-0 items-center justify-center rounded-ctl border transition-colors",
              local.selected
                ? "border-bright text-bright"
                : "border-line text-transparent",
            )}
            aria-hidden="true"
          >
            <Show when={local.selected}>
              <Icon name="check" size={12} />
            </Show>
          </span>
        </Show>
        <Show when={local.leading && !local.selectable}>
          <Icon name={local.leading!} class="text-dim" />
        </Show>
        <Text
          variant="label"
          tone={local.locked ? "dim" : local.selected ? "bright" : "default"}
          class="truncate"
        >
          {local.label}
        </Text>
      </span>
      <span
        class="flex shrink-0 items-center gap-2"
        onClick={
          // In selectable rows the right slot holds its own controls (Menu,
          // copy) — clicking them must not toggle the row's selection.
          local.selectable ? (e) => e.stopPropagation() : undefined
        }
      >
        <Show when={local.right}>{local.right}</Show>
        <Show when={local.locked}>
          <Icon name="lock" size={12} class="text-dim" />
        </Show>
      </span>
    </Dynamic>
  );
}
