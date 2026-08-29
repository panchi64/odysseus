import { Show, createMemo, createSignal, type JSX } from "solid-js";
import { useIsDesktop } from "~/lib/useMediaQuery";
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
import type { ViewDocumentRef } from "../model";
import {
  priorDocumentVersions,
  priorSnapshots,
  type PriorVersion,
  type ViewItem,
} from "../viewport";
import { ViewActionRow } from "./ViewActionRow";
import { ViewStage } from "./ViewStage";
import { ViewTimelineRail } from "./ViewTimelineRail";

type Mode = "preview" | "code";

const MODE_TABS: TabItem[] = [
  { value: "preview", label: "Preview" },
  { value: "code", label: "Code" },
];

/** The chat workspace's viewport — the conversation's **View** rendered beside the
 *  transcript (or, below `lg` / in fullscreen, in a full-screen sheet — the caller
 *  mounts this same component in either slot). One consolidated list of
 *  **versions**: a dropdown + a horizontal timeline rail, a PREVIEW / CODE toggle,
 *  and an action row (download, keeper, font size, wrap, refresh, fullscreen,
 *  collapse). The newest version is followed by default and shows its HTML preview
 *  first. The frontend only renders what the run's events describe; it decides
 *  nothing — all state (pin, tab, font, wrap, fullscreen) is the operator's own
 *  view preference, owned by the caller via `useViewerPersistence`. */
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
  onClose: () => void;
  /** Rendered only when provided — P5 wires the backend keeper flip. */
  onKeeper?: (item: ViewItem) => void;
  /** Relays an inline document edit to the backend (SAVE mints a new version). */
  onSaveDocument: (documentId: string, body: string) => Promise<void>;
  /** Fold in a version minted outside the run stream — an accepted AI suggestion
   *  (`DOC-3`) applies through the documents surface, so the View is told. */
  onDocumentVersion: (
    documentId: string,
    body: string,
    version: number | null,
  ) => void;
  /** A navigation (pin/tab change) is blocked on an unsaved document edit. */
  pendingNav?: boolean;
  onDiscardEdits?: () => void;
  onKeepEditing?: () => void;
  /** Captures the focusable panel container for the global keymap's focus-jump
   *  and focus-visible ring. */
  panelRef?: (el: HTMLDivElement) => void;
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
  // Prior document versions the selected document's CODE can diff against.
  const priorDocuments = createMemo<ViewDocumentRef[]>(() => {
    const sel = selected();
    return sel ? priorDocumentVersions(props.items, sel.key) : [];
  });

  // PREVIEW-only refresh, same condition the old loose header button used.
  const refreshVisible = () =>
    Boolean(selected()) && props.activeTab === "preview";

  // Whether the panel currently owns the whole screen rather than sharing it
  // with the transcript — the condition the caller mounts the fullscreen sheet
  // on. `fullscreen` alone is only half of it: below `lg` the panel is *always*
  // the sheet and the flag stays off, so a stage arm that needs room (the
  // suggestion review) would go unreachable on a narrow viewport if it read the
  // flag directly.
  const isDesktop = useIsDesktop();
  const expanded = (): boolean => props.fullscreen || !isDesktop();

  // Keeper only makes sense for a version the backend can actually bookmark: a
  // captured snapshot, or a *committed* document version (not the in-progress
  // version-0 head still streaming, and not a standalone live entry with neither).
  const keeperEligible = (): boolean => {
    const item = selected();
    return (
      Boolean(item?.snapshot) ||
      Boolean(item?.document && item.document.version >= 1)
    );
  };

  return (
    <div
      ref={props.panelRef}
      tabindex={-1}
      /* `p-2` keeps the header and the stage off the frame's rules — the
         surface is the framed box now, not a card with its own padding, so the
         breathing room has to come from here. */
      class="h-full p-2 outline-none transition-colors focus-visible:outline-1 focus-visible:outline-bright"
    >
      {/* `bare`: the frosted surface belongs to the framed region that
          `ConstructionReveal` draws, so the panel adds no fill, no shadow and
          no ring of its own. A card here was the parent container with rounded
          corners — a second box wrapped *around* the frame, when the frame is
          meant to be the edge of the thing itself. */}
      <Panel
        label="View"
        meta={
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
            onClose={props.onClose}
          />
        }
        bare
        flush
        fill
        class="h-full"
      >
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
          <div class="flex h-full min-h-0 flex-col">
            {/* Unsaved-edit guard: blocks a pin/tab change that would navigate away
                from the item currently being edited inline. Hard-cut, no dialog. */}
            <Show when={props.pendingNav}>
              <div class="flex items-center justify-between gap-2 px-3 py-2">
                <Text variant="label" tone="bright">
                  Unsaved edits
                </Text>
                <div class="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={props.onKeepEditing}
                  >
                    Keep editing
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={props.onDiscardEdits}
                  >
                    Discard edits
                  </Button>
                </div>
              </div>
            </Show>

            {/* Version dropdown + PREVIEW / CODE toggle. With a single version the
                dropdown collapses to its label. */}
            <div class="flex items-center gap-2 px-3 py-2">
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
                value={props.activeTab}
                onChange={(v) => props.onSelectTab(v as Mode)}
                class="shrink-0"
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
                    priorDocuments={priorDocuments()}
                    onSaveDocument={props.onSaveDocument}
                    onDocumentVersion={props.onDocumentVersion}
                    fontStep={props.fontStep}
                    softWrap={props.softWrap}
                    expanded={expanded()}
                  />
                )}
              </Show>
            </div>
          </div>
        </Show>
      </Panel>
    </div>
  );
}
