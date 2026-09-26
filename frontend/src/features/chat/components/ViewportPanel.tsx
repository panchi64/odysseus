import { Show, createMemo, createSignal, type JSX } from "solid-js";
import {
  EmptyState,
  Segmented,
  Select,
  Text,
  type SegmentedOption,
  type SelectOption,
} from "~/ui";
import {
  priorSnapshots,
  type PriorVersion,
  type ViewItem,
} from "../viewport/viewItems";
import { PaneToolbar } from "./PaneFrame";
import { ViewActionRow } from "./ViewActionRow";
import { ViewStage } from "./ViewStage";
import { ViewTimelineRail } from "./ViewTimelineRail";

type Mode = "preview" | "code";

const MODE_OPTIONS: SegmentedOption<Mode>[] = [
  { value: "preview", label: "Preview" },
  { value: "code", label: "Code" },
];

/** The chat workspace's viewport — the conversation's **View** rendered beside the
 *  transcript (or, below `lg` / in fullscreen, in a full-screen sheet — the caller
 *  mounts this same component in either slot). One consolidated list of
 *  **versions**: a dropdown + a horizontal timeline rail, a PREVIEW / CODE toggle,
 *  and an action row (download, keeper, font size, wrap, refresh, fullscreen) lent
 *  to the pane header. The newest version is followed by default and shows its HTML
 *  preview first. The frontend only renders what the run's events describe; it
 *  decides nothing — all state (pin, tab, font, wrap, fullscreen) is the operator's
 *  own view preference, owned by the caller via `useViewerPersistence`. */
export function ViewportPanel(props: {
  items: ViewItem[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  activeTab: Mode;
  onSelectTab: (tab: Mode) => void;
  fontStep: number;
  onFontStep: (step: number) => void;
  softWrap: boolean;
  onToggleWrap: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  /** Rendered only when provided — P5 wires the backend keeper flip. */
  onKeeper?: (item: ViewItem) => void;
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
  // Manual reload nonce: bumping it reloads only the live/preview iframe in place
  // (the one-click equivalent of closing and reopening), without tearing down the
  // surrounding stage — so a refresh no longer refetches the file tree or flashes.
  const [reloadKey, setReloadKey] = createSignal(0);

  // Versions for the dropdown, newest first.
  const versionOptions = createMemo<SelectOption[]>(() =>
    [...props.items].reverse().map((i) => ({ value: i.key, label: i.label })),
  );

  // Prior snapshots the selected version's CODE can diff against.
  const priorVersions = createMemo<PriorVersion[]>(() => {
    const sel = selected();
    return sel ? priorSnapshots(props.items, sel.key) : [];
  });
  // PREVIEW-only refresh, same condition the old loose header button used.
  const refreshVisible = () =>
    Boolean(selected()) && props.activeTab === "preview";

  // Keeper only makes sense for a version the backend can actually bookmark — a
  // captured snapshot, not a standalone live entry with none.
  const keeperEligible = (): boolean => Boolean(selected()?.snapshot);

  return (
    // No `tabindex` and no focus ring: the focusable container is the panel itself
    // (`ChatViewportMounts`), which is what "focus is in the panel" has to mean once
    // the panel can hold more than this one surface.
    <div class="flex h-full min-h-0 flex-col">
      {/* The actions are a toolbar, not a title, so they ride the pane's own header
          rather than a row of their own under it — while staying here, since they
          read stage state (the selected version, the reload nonce) only this
          component holds. */}
      <PaneToolbar>
        <ViewActionRow
          keeper={selected()?.keeper}
          onKeeper={
            props.onKeeper && keeperEligible()
              ? () => props.onKeeper!(selected()!)
              : undefined
          }
          fontStep={props.fontStep}
          onFontStep={props.onFontStep}
          softWrap={props.softWrap}
          onToggleWrap={props.onToggleWrap}
          onRefresh={
            refreshVisible() ? () => setReloadKey((k) => k + 1) : undefined
          }
          fullscreen={props.fullscreen}
          onToggleFullscreen={props.onToggleFullscreen}
        />
      </PaneToolbar>
      <Show
        when={props.items.length > 0}
        fallback={
          <EmptyState
            icon="eye"
            message="Nothing to show yet"
            hint="Pages, charts, files, and live servers from this conversation appear here."
          />
        }
      >
        {/* Which version, and which face of it — one row, wrapping when the pane is
            too narrow for both. With a single version the dropdown collapses to its
            label. */}
        <div class="flex shrink-0 flex-wrap items-center gap-2 px-3 py-2">
          <Show
            when={props.items.length > 1}
            fallback={
              <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
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
          <Segmented
            aria-label="Preview or code"
            fill={false}
            options={MODE_OPTIONS}
            value={props.activeTab}
            onChange={props.onSelectTab}
          />
        </div>

        <ViewTimelineRail
          items={props.items}
          selectedKey={selected()?.key ?? null}
          followingLatest={props.selectedKey === null}
          onSelect={props.onSelect}
        />

        <div class="min-h-0 flex-1">
          {/* The stage stays mounted and reacts to the selected version in place
              (the live head's iframe survives a relabel when a newer version is
              minted on the same server); only the refresh nonce reloads the iframe. */}
          <Show when={selected()}>
            {(entry) => (
              <ViewStage
                entry={entry()}
                mode={props.activeTab}
                reloadKey={reloadKey()}
                priorVersions={priorVersions()}
                fontStep={props.fontStep}
                softWrap={props.softWrap}
              />
            )}
          </Show>
        </div>
      </Show>
    </div>
  );
}
