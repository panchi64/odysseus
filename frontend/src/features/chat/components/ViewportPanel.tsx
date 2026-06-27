import { Match, Show, Switch, createMemo, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  Panel,
  StatusDot,
  Tabs,
  Text,
  type TabItem,
} from "~/ui";
import type { ViewItem } from "../viewport";
import { ViewLiveContent } from "./ViewLiveContent";
import { ViewVersionContent } from "./ViewVersionContent";

type LiveItem = Extract<ViewItem, { kind: "live" }>;
type VersionItem = Extract<ViewItem, { kind: "version" }>;

/** The chat workspace's viewport — the conversation's **View** rendered beside the
 *  transcript: the current item on stage plus a version timeline to flip back and
 *  compare. The frontend only renders what the run's events describe; it decides
 *  nothing. Empty until the agent shows something. */
export function ViewportPanel(props: {
  items: ViewItem[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onClose: () => void;
}): JSX.Element {
  // The item actually shown: the selection if it's still present, else the newest
  // (last) — so a stale selection or a fresh thread always lands on something real.
  const selected = createMemo<ViewItem | undefined>(() => {
    const items = props.items;
    if (items.length === 0) return undefined;
    return (
      items.find((i) => i.key === props.selectedKey) ?? items[items.length - 1]
    );
  });
  // The timeline as design-system tabs: versions sort first (so a version's index
  // is its 1-based number), the live head last with a live-status dot.
  const tabs = createMemo<TabItem[]>(() =>
    props.items.map((item, i) => ({
      value: item.key,
      label:
        item.kind === "live" ? (
          <span class="flex items-center gap-1">
            <StatusDot status="live" pulse />
            LIVE
          </span>
        ) : (
          `V${i + 1}`
        ),
    })),
  );

  return (
    <Panel
      label="VIEW"
      meta={
        <span class="flex min-w-0 items-center gap-2">
          <Show when={selected()}>
            {(item) => (
              <Text variant="micro" tone="dim" class="max-w-xs truncate">
                {item().label}
              </Text>
            )}
          </Show>
          <Button
            variant="ghost"
            size="sm"
            leading="chevron-right"
            aria-label="Collapse viewport"
            onClick={() => props.onClose()}
          />
        </span>
      }
      flush
      fill
      class="h-full"
    >
      <Show
        when={props.items.length > 0}
        fallback={
          <EmptyState
            icon="eye"
            message="NOTHING TO SHOW YET"
            hint="Pages, charts, files, and live servers from this conversation appear here."
          />
        }
      >
        <div class="flex h-full min-h-0 flex-col">
          {/* Version timeline — flip back through versions to compare; the live
              head (when running) is the head of the line. */}
          <Show when={props.items.length > 1}>
            <Tabs
              items={tabs()}
              value={selected()?.key ?? ""}
              onChange={props.onSelect}
              class="overflow-x-auto"
            />
          </Show>
          <div class="min-h-0 flex-1">
            <Show when={selected()}>
              {(item) => (
                <Switch>
                  <Match when={item().kind === "live"}>
                    <ViewLiveContent live={(item() as LiveItem).live} />
                  </Match>
                  <Match when={item().kind === "version"}>
                    <ViewVersionContent
                      version={(item() as VersionItem).version}
                    />
                  </Match>
                </Switch>
              )}
            </Show>
          </div>
        </div>
      </Show>
    </Panel>
  );
}
