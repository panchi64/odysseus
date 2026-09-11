import { For, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";
import type { IconName } from "../icons/registry";
import { Tooltip } from "./Tooltip";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
  /** Hover/focus explanation of what picking this does. */
  description?: string;
}

export interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Required: a radiogroup with no name is a set of buttons to a screen
   *  reader. */
  "aria-label": string;
  /** Segments share the width equally. Off for a control sized by its labels. */
  fill?: boolean;
  class?: string;
}

/**
 * A row of mutually exclusive choices — one is always picked (§10.8 Controls).
 *
 * **Not `Tabs`, and the difference is what the control means.** A tab strip picks
 * which of several panels to *show*; this picks a value, and the thing it changes
 * may be nowhere near it. That is why it is a `radiogroup` and not a `tablist`,
 * and the distinction is not pedantry — it is what a screen reader announces, and
 * "tab 1 of 3" is a lie about a control that is not revealing anything.
 *
 * **The selection is a raised fill and nothing else.** No track behind the set:
 * `surface-sunken` is the fill of a turn in a transcript, not a groove for a
 * control to sit in, and a second surface under the segments makes a small
 * control read as a component with a frame. Selection lifts to `surface-raised`,
 * the same way the rail marks the page you are on — never a coloured pill, which
 * would spend the accent on a control whose whole job may be *choosing* the
 * accent.
 *
 * **Roving tabindex, because a radiogroup is one stop.** Tab reaches the control
 * and the arrow keys move within it; every segment being separately tabbable is
 * the wrong model and makes a three-option control cost three tabs to pass.
 */
export function Segmented<T extends string>(
  props: SegmentedProps<T>,
): JSX.Element {
  const [local] = splitProps(props, [
    "options",
    "value",
    "onChange",
    "aria-label",
    "fill",
    "class",
  ]);

  /** Move the selection by `step`, wrapping — standard radiogroup behaviour, and
   *  it *selects* rather than merely focusing, which is what a radiogroup does. */
  const move = (step: number): void => {
    const items = local.options;
    if (items.length === 0) return;
    const at = items.findIndex((o) => o.value === local.value);
    const next = items[(at + step + items.length) % items.length];
    local.onChange(next.value);
  };

  const onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") move(1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") move(-1);
    else return;
    e.preventDefault();
  };

  return (
    <div
      role="radiogroup"
      aria-label={local["aria-label"]}
      class={cx("flex items-center gap-1", local.class)}
      onKeyDown={onKeyDown}
    >
      <For each={local.options}>
        {(option) => {
          const active = () => option.value === local.value;
          const segment = (
            <button
              type="button"
              role="radio"
              aria-checked={active()}
              // One stop for the whole group: the picked segment is the one Tab
              // lands on, and the arrows do the rest.
              tabindex={active() ? 0 : -1}
              onClick={() => local.onChange(option.value)}
              class={cx(
                "flex items-center justify-center gap-1.5 rounded-ctl px-3 py-1.5 text-body font-sans whitespace-nowrap transition-colors",
                // Focus is neutral and carried by a shadow, so it shifts no
                // layout and never competes with the accent (§10.8).
                "outline-none focus-visible:shadow-focus",
                local.fill !== false && "min-w-0 flex-1",
                // The picked segment is separated from the rest on three axes at
                // once — it lifts to `surface-raised`, it carries `shadow-1`'s
                // hairline ring so it reads as an object rather than a tint, and
                // it is the only one at medium weight. A raised fill alone was
                // too close a step off the rail's own surface to find at a
                // glance, and the answer is not a coloured pill: this control
                // may be the one *choosing* the accent, so spending the accent
                // on it says the wrong thing.
                active()
                  ? "bg-raised text-bright font-medium shadow-1"
                  : "font-normal text-dim hover:bg-raised hover:text-text",
              )}
            >
              {option.icon ? <Icon name={option.icon} size={14} /> : null}
              {option.label}
            </button>
          );
          return option.description ? (
            <Tooltip
              delay={600}
              side="bottom"
              label={option.description}
              class={cx(local.fill !== false && "min-w-0 flex-1")}
            >
              {segment}
            </Tooltip>
          ) : (
            segment
          );
        }}
      </For>
    </div>
  );
}
