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
  class?: string;
}

/** Horizontal tab strip. Active tab = bright text + 2px bottom emphasis. */
export function Tabs(props: TabsProps): JSX.Element {
  const [local] = splitProps(props, ["items", "value", "onChange", "class"]);
  return (
    <div
      class={cx(
        // Scrolls rather than wrapping or clipping when the labels outgrow the
        // container — a tab strip that silently hides its last tab is worse than one
        // with a scrollbar.
        "scrollbar-thin flex items-stretch overflow-x-auto border-b border-line",
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
                "-mb-px border-b-2 px-3 py-2 text-label uppercase tracking-label font-mono transition-colors",
                active()
                  ? "border-bright text-bright"
                  : "border-transparent text-dim hover:text-text",
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
