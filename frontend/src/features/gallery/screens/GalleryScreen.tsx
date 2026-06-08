import {
  createEffect,
  createMemo,
  createSignal,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListToolbar,
  LoadingText,
  PageHeader,
  Panel,
  Stack,
  Tabs,
  Text,
  confirm,
  toast,
} from "~/ui";
import { createListView } from "~/lib/list";
import { bytes } from "~/lib/format";
import { useAlbums, useMedia } from "../data";
import { MediaTile } from "../components/MediaTile";
import { MediaDetailDrawer } from "../components/MediaDetailDrawer";
import type { MediaItem } from "../model";

export function GalleryScreen(): JSX.Element {
  const albums = useAlbums();
  const media = useMedia();
  const [selectedAlbum, setSelectedAlbum] = createSignal("all");
  const [selectedItem, setSelectedItem] = createSignal<MediaItem | null>(null);
  const [drawerOpen, setDrawerOpen] = createSignal(false);
  const [items, setItems] = createSignal<MediaItem[]>([]);
  const [importing, setImporting] = createSignal(false);
  const [selectMode, setSelectMode] = createSignal(false);

  let seeded = false;
  createEffect(() => {
    const data = media();
    if (!seeded && data) {
      seeded = true;
      setItems(data.slice());
    }
  });

  const inAlbum = () => {
    const album = selectedAlbum();
    return album === "all" ? items() : items().filter((m) => m.album === album);
  };

  const view = createListView({
    source: inAlbum,
    search: (m) => `${m.title} ${m.tags.join(" ")}`,
    sorts: {
      recent: {
        label: "DATE",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
      size: { label: "SIZE", compare: (a, b) => a.sizeBytes - b.sizeBytes },
      type: { label: "TYPE", compare: (a, b) => a.type.localeCompare(b.type) },
    },
    initialSort: "recent",
    initialDir: "desc",
    id: (m) => m.id,
  });

  // One pass for all header stats instead of four walks over the media list.
  const stats = createMemo(() => {
    let images = 0;
    let videos = 0;
    let favorites = 0;
    let byteSum = 0;
    for (const m of items()) {
      if (m.type === "image") images++;
      else if (m.type === "video") videos++;
      if (m.favorite) favorites++;
      byteSum += m.sizeBytes;
    }
    return { images, videos, favorites, bytes: byteSum };
  });

  function toggleFavorite(id: string) {
    setItems((prev) =>
      prev.map((m) => (m.id === id ? { ...m, favorite: !m.favorite } : m)),
    );
  }

  function openItem(item: MediaItem) {
    setSelectedItem(item);
    setDrawerOpen(true);
  }

  function toggleSelectMode(): void {
    setSelectMode((on) => {
      if (on) view.clearSelection();
      return !on;
    });
  }

  async function handleBulkDelete(): Promise<void> {
    const targets = view.selectedItems();
    if (!targets.length) return;
    const ok = await confirm({
      title: `Delete ${targets.length} item${targets.length > 1 ? "s" : ""}?`,
      detail: "This action cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    const ids = new Set(targets.map((t) => t.id));
    const removed = items().filter((m) => ids.has(m.id));
    setItems((prev) => prev.filter((m) => !ids.has(m.id)));
    view.clearSelection();
    toast.success(
      `Deleted ${targets.length} item${targets.length > 1 ? "s" : ""}`,
      {
        action: {
          label: "UNDO",
          onClick: () => setItems((prev) => [...removed, ...prev]),
        },
      },
    );
  }

  function handleImport() {
    if (importing()) return;
    setImporting(true);
    setTimeout(() => {
      setImporting(false);
      toast.success("Imported 1 file — gallery updated.");
    }, 1500);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="GALLERY"
        subtitle="Media library — AI-generated, captured, and imported."
        assetId="ODY-GAL-01.0"
        actions={
          <Button
            variant="ghost"
            leading="upload"
            disabled={importing()}
            onClick={handleImport}
          >
            {importing() ? "IMPORTING…" : "IMPORT"}
          </Button>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={media()}>
          <InstrumentBand
            items={[
              { label: "TOTAL", value: String(items().length) },
              { label: "STORAGE", value: bytes(stats().bytes), tone: "info" },
              { label: "IMAGES", value: String(stats().images) },
              { label: "VIDEO", value: String(stats().videos) },
              {
                label: "FAVORITES",
                value: String(stats().favorites),
                tone: "warn",
              },
            ]}
          />
        </Show>
      </Suspense>

      <div class="flex gap-4 min-h-0">
        {/* Album sidebar */}
        <aside class="hidden w-44 shrink-0 lg:block">
          <Panel label="ALBUMS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <For each={albums()}>
                {(album) => (
                  <button
                    type="button"
                    onClick={() => setSelectedAlbum(album.id)}
                    class="w-full flex items-center justify-between border-b border-line px-3 py-2 text-left transition-colors hover:bg-raised last:border-b-0"
                    classList={{ "bg-raised": selectedAlbum() === album.id }}
                  >
                    <Text
                      variant="label"
                      tone={selectedAlbum() === album.id ? "bright" : "dim"}
                    >
                      {album.name}
                    </Text>
                    <Text variant="micro" tone="dim">
                      {album.count}
                    </Text>
                  </button>
                )}
              </For>
            </Suspense>
          </Panel>
        </aside>

        {/* Grid */}
        <div class="flex-1 min-w-0">
          {/* Mobile album tabs */}
          <Suspense>
            <Show when={albums()}>
              <Tabs
                class="mb-4 lg:hidden"
                items={(albums() ?? []).map((a) => ({
                  value: a.id,
                  label: a.name,
                }))}
                value={selectedAlbum()}
                onChange={setSelectedAlbum}
              />
            </Show>
          </Suspense>

          <Stack gap={3}>
            <div class="flex items-center gap-3">
              <div class="flex-1">
                <ListToolbar
                  query={view.query()}
                  onQueryChange={view.setQuery}
                  placeholder="Search media…"
                  sortKey={view.sortKey()}
                  sortOptions={view.sortOptions}
                  onSortChange={view.setSort}
                  dir={view.dir()}
                  onToggleDir={view.toggleDir}
                  count={view.count()}
                  total={view.total()}
                  allSelected={view.allSelected()}
                  onToggleAll={selectMode() ? view.toggleAll : undefined}
                  selectedCount={view.selectedCount()}
                  onClearSelection={view.clearSelection}
                  bulkActions={
                    <Button
                      variant="danger"
                      size="sm"
                      leading="trash"
                      onClick={() => void handleBulkDelete()}
                    >
                      DELETE
                    </Button>
                  }
                />
              </div>
              <Button
                variant={selectMode() ? "primary" : "ghost"}
                size="sm"
                leading="check"
                onClick={toggleSelectMode}
              >
                {selectMode() ? "DONE" : "SELECT"}
              </Button>
            </div>

            <Suspense fallback={<LoadingText />}>
              <Show
                when={view.items().length}
                fallback={
                  <EmptyState
                    icon="image"
                    message={view.isFiltered() ? "NO MATCHES" : "NO MEDIA"}
                    hint={
                      view.isFiltered()
                        ? "No media matches your search."
                        : "Import files or generate with AI to populate the gallery."
                    }
                  />
                }
              >
                <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                  <For each={view.items()}>
                    {(item) => (
                      <MediaTile
                        item={item}
                        selectMode={selectMode()}
                        selected={
                          selectMode()
                            ? view.isSelected(item.id)
                            : selectedItem()?.id === item.id
                        }
                        onSelect={() =>
                          selectMode()
                            ? view.toggleOne(item.id)
                            : openItem(item)
                        }
                        onToggleFavorite={() => toggleFavorite(item.id)}
                      />
                    )}
                  </For>
                </div>
              </Show>
            </Suspense>
          </Stack>
        </div>
      </div>

      <MediaDetailDrawer
        item={selectedItem()}
        open={drawerOpen()}
        onClose={() => setDrawerOpen(false)}
      />
    </Stack>
  );
}
