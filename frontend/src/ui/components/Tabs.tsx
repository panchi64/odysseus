import { For, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface TabItem {
  value: string;
  label: string;
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
      class={cx("flex items-stretch border-b border-line", local.class)}
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
