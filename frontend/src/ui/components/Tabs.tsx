import { For, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface TabItem {
  value: string;
  /** Usually a plain string; accepts JSX for a tab that carries a glyph/dot
   *  alongside its label (e.g. a live-status indicator). */
  label: string | JSX.Element;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  /** Tabs share the width equally and the strip becomes a band of its own.
   *
   *  For a strip that *is* the boundary between a region's header and its
   *  content rather than a control sitting inside the header — the viewport's
   *  PREVIEW/CODE. A full-width set of two reads as a division; the same two
   *  tabs sized to their labels read as a pair of buttons that happen to be
   *  there. */
  fill?: boolean;
  class?: string;
}

/** Horizontal tab strip. The selected tab lifts to `surface-raised` and is the
 *  only one at medium weight. */
export function Tabs(props: TabsProps): JSX.Element {
  const [local] = splitProps(props, [
    "items",
    "value",
    "onChange",
    "fill",
    "class",
  ]);
  return (
    <div
      class={cx(
        // Scrolls rather than wrapping or clipping when the labels outgrow the
        // container — a tab strip that silently hides its last tab is worse than one
        // with a scrollbar.
        // No rule under the strip (§7): the selected tab's own fill marks the
        // set, and the old border-b drew a line across every screen that had
        // tabs whether or not anything needed dividing there.
        "scrollbar-thin flex items-stretch gap-1 overflow-x-auto",
        // A filling strip draws the one rule §7 sanctions: it is not decoration
        // between two regions that space already separates, it is the edge of
        // the header itself, and the content below starts against it.
        local.fill && "border-b border-line px-2 py-1.5",
        local.class,
      )}
      role="tablist"
    >
      <For each={local.items}>
        {(tab) => {
          const active = () => tab.value === local.value;
          return (
            <button
              type="button"
              role="tab"
              aria-selected={active()}
              onClick={() => local.onChange(tab.value)}
              class={cx(
                "rounded-ctl px-3 py-1.5 text-body font-sans font-medium whitespace-nowrap transition-colors",
                active()
                  ? "bg-raised text-bright"
                  : "text-dim hover:bg-raised hover:text-text",
              )}
            >
              {tab.label}
            </button>
          );
        }}
      </For>
    </div>
  );
}
