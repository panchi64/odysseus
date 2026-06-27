import {
  Match,
  Show,
  Switch,
  createMemo,
  createSignal,
  type JSX,
} from "solid-js";
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
import { ViewSnapshotContent } from "./ViewSnapshotContent";

type LiveItem = Extract<ViewItem, { kind: "live" }>;
type VersionItem = Extract<ViewItem, { kind: "version" }>;
type SnapshotItem = Extract<ViewItem, { kind: "snapshot" }>;

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
  // Manual reload nonce: bumping it remounts whatever the viewport is showing (a
  // live frame loaded too early, or a static version), forcing a fresh fetch — the
  // one-click equivalent of closing and reopening the panel.
  const [reloadKey, setReloadKey] = createSignal(0);
  // Keys the content render: changes when the selection changes *or* on a refresh
  // bump, so a keyed Show recreates the frame/snapshot on either.
  const contentKey = createMemo(() => {
    const item = selected();
    return item ? `${item.key}#${reloadKey()}` : "";
  });
  // The timeline as design-system tabs: versions (V1, V2…) first, then workspace
  // snapshots (S1, S2…), then the live head with a live-status dot. Each kind is
  // numbered within itself so the short codes stay stable as the other kind grows.
  const tabs = createMemo<TabItem[]>(() => {
    let versionN = 0;
    let snapshotN = 0;
    return props.items.map((item) => ({
      value: item.key,
      label:
        item.kind === "live" ? (
          <span class="flex items-center gap-1">
            <StatusDot status="live" pulse />
            LIVE
          </span>
        ) : item.kind === "snapshot" ? (
          `S${++snapshotN}`
        ) : (
          `V${++versionN}`
        ),
    }));
  });

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
          <Show when={selected()}>
            <Button
              variant="ghost"
              size="sm"
              leading="refresh"
              aria-label="Reload view"
              onClick={() => setReloadKey((k) => k + 1)}
            />
          </Show>
          <Button
            variant="ghost"
            size="sm"
            leading="panel-right"
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
            {/* Keyed on selection + refresh nonce: a new key recreates the frame,
                so switching items and the manual refresh both force a fresh load. */}
            <Show keyed when={contentKey()}>
              <Switch>
                <Match when={selected()?.kind === "live"}>
                  <ViewLiveContent live={(selected() as LiveItem).live} />
                </Match>
                <Match when={selected()?.kind === "version"}>
                  <ViewVersionContent
                    version={(selected() as VersionItem).version}
                  />
                </Match>
                <Match when={selected()?.kind === "snapshot"}>
                  <ViewSnapshotContent
                    snapshot={(selected() as SnapshotItem).snapshot}
                  />
                </Match>
              </Switch>
            </Show>
          </div>
        </div>
      </Show>
    </Panel>
  );
}
