import { Show, createMemo, createSignal, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  Panel,
  Select,
  Tabs,
  Text,
  type SelectOption,
  type TabItem,
} from "~/ui";
import { priorSnapshots, type PriorVersion, type ViewItem } from "../viewport";
import { ViewStage } from "./ViewStage";

type Mode = "preview" | "code";

const MODE_TABS: TabItem[] = [
  { value: "preview", label: "PREVIEW" },
  { value: "code", label: "CODE" },
];

/** The chat workspace's viewport — the conversation's **View** rendered beside the
 *  transcript. One consolidated list of **versions** (a dropdown) with a PREVIEW / CODE
 *  toggle; the newest version is followed by default and shows its HTML preview first.
 *  The frontend only renders what the run's events describe; it decides nothing.
 *  Empty until the agent shows something. */
export function ViewportPanel(props: {
  items: ViewItem[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onClose: () => void;
}): JSX.Element {
  // The version actually shown: the selection if still present, else the newest
  // (last) — so a stale selection or a fresh thread always lands on the latest.
  const selected = createMemo<ViewItem | undefined>(() => {
    const items = props.items;
    if (items.length === 0) return undefined;
    return (
      items.find((i) => i.key === props.selectedKey) ?? items[items.length - 1]
    );
  });
  // PREVIEW first — the HTML render is shown before the code whenever a View opens.
  const [mode, setMode] = createSignal<Mode>("preview");
  // Manual reload nonce: bumping it remounts whatever the viewport is showing,
  // forcing a fresh fetch — the one-click equivalent of closing and reopening.
  const [reloadKey, setReloadKey] = createSignal(0);
  // Keys the stage: changes when the selected version changes *or* on a refresh
  // bump (mode is handled reactively, so toggling PREVIEW/CODE keeps the version).
  const contentKey = createMemo(() => {
    const item = selected();
    return item ? `${item.key}#${reloadKey()}` : "";
  });

  // Versions for the dropdown, newest first.
  const versionOptions = createMemo<SelectOption[]>(() =>
    [...props.items].reverse().map((i) => ({ value: i.key, label: i.label })),
  );

  // Prior snapshots the selected version's CODE can diff against.
  const priorVersions = createMemo<PriorVersion[]>(() => {
    const sel = selected();
    return sel ? priorSnapshots(props.items, sel.key) : [];
  });

  return (
    <Panel
      label="VIEW"
      meta={
        <span class="flex min-w-0 items-center gap-2">
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
          {/* Version dropdown + PREVIEW / CODE toggle. With a single version the
              dropdown collapses to its label. */}
          <div class="flex items-center gap-2 border-b border-line px-3 py-2">
            <Show
              when={props.items.length > 1}
              fallback={
                <Text
                  variant="micro"
                  tone="dim"
                  class="min-w-0 flex-1 truncate"
                >
                  {selected()?.label}
                </Text>
              }
            >
              <Select
                aria-label="Select version"
                class="min-w-0 flex-1"
                options={versionOptions()}
                value={selected()?.key}
                onChange={props.onSelect}
              />
            </Show>
            <Tabs
              items={MODE_TABS}
              value={mode()}
              onChange={(v) => setMode(v as Mode)}
              class="shrink-0"
            />
          </div>
          <div class="min-h-0 flex-1">
            {/* Keyed on the version + refresh nonce: picking another version (or the
                manual refresh) remounts the stage; toggling PREVIEW/CODE does not. */}
            <Show keyed when={contentKey()}>
              <ViewStage
                entry={selected()!}
                mode={mode()}
                priorVersions={priorVersions()}
              />
            </Show>
          </div>
        </div>
      </Show>
    </Panel>
  );
}
