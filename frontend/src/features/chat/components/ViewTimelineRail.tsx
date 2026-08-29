import { For, Show, createEffect, on, type JSX } from "solid-js";
import { Icon, Text, cx } from "~/ui";
import type { ViewItem } from "../viewport";
import {
  classifyViewItem,
  viewItemTimeLabel,
  viewItemVersionLabel,
} from "./ViewChip";

/** A dense, horizontal strip of every View item in chronological order, between
 *  the panel header and the stage — a scrubber for the whole conversation's View.
 *  Clicking a cell pins it (or clears the pin when the clicked cell is already the
 *  latest, mirroring the version dropdown); the followed/pinned cell is brightest
 *  and auto-scrolls into view. Hidden with fewer than two items — a single item
 *  has nothing to scrub between. Mechanical, dense, monochrome. */
export function ViewTimelineRail(props: {
  items: ViewItem[];
  /** The item actually shown (pinned, or the latest when following). */
  selectedKey: string | null;
  /** True when nothing is pinned (following the latest as new versions arrive). */
  followingLatest: boolean;
  onSelect: (key: string) => void;
}): JSX.Element {
  const cellRefs = new Map<string, HTMLButtonElement>();

  // Keep the active cell in view whenever the followed/pinned item changes —
  // including when a new version arrives while following latest.
  createEffect(
    on(
      () => props.selectedKey,
      (key) => {
        if (!key) return;
        cellRefs.get(key)?.scrollIntoView({ block: "nearest" });
      },
    ),
  );

  return (
    <Show when={props.items.length >= 2}>
      <div
        role="listbox"
        aria-label="Version timeline"
        class="scrollbar-thin flex shrink-0 items-stretch overflow-x-auto bg-surface"
      >
        <For each={props.items}>
          {(item) => {
            const active = () => item.key === props.selectedKey;
            const cls = classifyViewItem(item);
            const time = viewItemTimeLabel(item);
            const version = viewItemVersionLabel(item);
            return (
              <button
                type="button"
                ref={(el) => cellRefs.set(item.key, el)}
                onClick={() => props.onSelect(item.key)}
                role="option"
                aria-selected={active()}
                class={cx(
                  "flex shrink-0 flex-col items-start gap-0.5 border-r border-line px-2 py-1.5 text-left transition-colors",
                  active() ? "bg-raised" : "hover:bg-raised",
                )}
              >
                <span class="flex items-center gap-1">
                  <Icon
                    name={cls.icon}
                    size={11}
                    class={active() ? "text-bright" : "text-dim"}
                  />
                  <Text variant="micro" tone={active() ? "bright" : "dim"}>
                    {cls.word}
                  </Text>
                  <Show when={item.keeper}>
                    <Icon
                      name="pin"
                      size={10}
                      class={active() ? "text-bright" : "text-dim"}
                    />
                  </Show>
                </span>
                <span class="flex items-center gap-1">
                  <Show when={version}>
                    <Text variant="micro" tone={active() ? "bright" : "dim"}>
                      {version}
                    </Text>
                  </Show>
                  <Show when={time}>
                    <Text variant="micro" tone="dim">
                      {time}
                    </Text>
                  </Show>
                  <Show when={item.isLatest && props.followingLatest}>
                    <Text variant="micro" tone="dim" class="tracking-label">
                      Latest
                    </Text>
                  </Show>
                </span>
              </button>
            );
          }}
        </For>
      </div>
    </Show>
  );
}
