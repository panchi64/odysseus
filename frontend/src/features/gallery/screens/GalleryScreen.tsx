import {
  createEffect,
  createMemo,
  createSignal,
  For,
  Show,
  type JSX,
} from "solid-js";
import { createStore, reconcile } from "solid-js/store";
import {
  Button,
  EmptyState,
  ErrorState,
  Icon,
  InstrumentBand,
  Lightbox,
  ListToolbar,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  Resource,
  Row,
  Stack,
  Tabs,
  Text,
  confirm,
  toast,
  type LightboxItem,
} from "~/ui";
import { createListView } from "~/lib/list";
import { useAuthedBlobUrl } from "~/lib/api";
import { bytes } from "~/lib/format";
import {
  addToAlbum,
  createAlbum,
  deleteAlbum,
  deleteMedia,
  downloadImage,
  fullImagePath,
  importImage,
  refetchAlbums,
  refetchMedia,
  removeFromAlbum,
  renameAlbum,
  setFavorite,
  setKbExcluded,
  useAlbums,
  useMedia,
} from "../data";
import { MediaTile } from "../components/MediaTile";
import { MediaDetailDrawer } from "../components/MediaDetailDrawer";
import { AlbumNameDialog } from "../components/AlbumNameDialog";
import type { Album, MediaItem } from "../model";

/** Diegetic asset id derived from the capture date (design §7). */
const assetIdOf = (m: MediaItem): string =>
  `ODY-GAL-${m.createdAt.slice(0, 10).replace(/-/g, "")}`;

type AlbumDialogState = { mode: "create" } | { mode: "rename"; album: Album };

export function GalleryScreen(): JSX.Element {
  const media = useMedia();
  const albums = useAlbums();

  // A reconciled mirror of the media resource: refetches keep stable per-row
  // identities (keyed on id), so a mutation updates only the changed tiles and
  // never re-downloads every thumbnail. Presentation-only — the backend remains
  // the source of truth; this just makes the view stable across refetches.
  const [items, setItems] = createStore<MediaItem[]>([]);
  createEffect(() => {
    const data = media();
    if (data) setItems(reconcile(data, { key: "id" }));
  });

  const [selectedAlbum, setSelectedAlbum] = createSignal("all");
  const [selectMode, setSelectMode] = createSignal(false);
  const [importing, setImporting] = createSignal(false);

  // Detail drawer + lightbox both target a single image; the drawer holds the
  // per-image controls, the lightbox is the quick full-screen view.
  const [detailItem, setDetailItem] = createSignal<MediaItem | null>(null);
  const [drawerOpen, setDrawerOpen] = createSignal(false);
  const [lightboxOpen, setLightboxOpen] = createSignal(false);
  const [lightboxIndex, setLightboxIndex] = createSignal(0);

  const [albumDialog, setAlbumDialog] = createSignal<AlbumDialogState | null>(
    null,
  );

  // Album reads must never throw: if `/gallery/albums` errors, reading the resource
  // accessor re-throws, and the shell's ErrorBoundary would replace the whole gallery —
  // the grid included — with one failure message. Derive from `.latest`/`.error` so a
  // transient album failure degrades to an empty sidebar (with its own retry) instead of
  // taking the grid down with it. The boundary is the net, not the plan.
  const albumList = createMemo<Album[]>(() =>
    albums.error ? [] : (albums.latest ?? []),
  );
  const customAlbums = createMemo<Album[]>(() =>
    albumList().filter((a) => !a.system),
  );

  const inAlbum = (): MediaItem[] => {
    const album = selectedAlbum();
    return album === "all"
      ? items
      : items.filter((m) => m.albumIds.includes(album));
  };

  const view = createListView<MediaItem>({
    source: inAlbum,
    search: (m) => `${m.title} ${m.tags.join(" ")}`,
    sorts: {
      recent: {
        label: "DATE",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
      size: { label: "SIZE", compare: (a, b) => a.sizeBytes - b.sizeBytes },
      name: {
        label: "NAME",
        compare: (a, b) => a.title.localeCompare(b.title),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
    id: (m) => m.id,
  });

  // One pass for all header stats instead of separate walks over the list.
  const stats = createMemo(() => {
    let favorites = 0;
    let excluded = 0;
    let byteSum = 0;
    for (const m of items) {
      if (m.favorite) favorites++;
      if (m.kbExcluded) excluded++;
      byteSum += m.sizeBytes;
    }
    return { favorites, excluded, bytes: byteSum };
  });

  // The lightbox resolves only the active item's full image; siblings stay lazy.
  const activeFull = useAuthedBlobUrl(() => {
    if (!lightboxOpen()) return undefined;
    const m = view.items()[lightboxIndex()];
    return m ? fullImagePath(m.id) : undefined;
  });
  const lightboxItems = createMemo<LightboxItem[]>(() =>
    view.items().map((m, i) => ({
      src: i === lightboxIndex() ? activeFull() : undefined,
      error: i === lightboxIndex() ? activeFull.error !== undefined : false,
      filename: m.title,
      size: m.sizeBytes,
      assetId: assetIdOf(m),
    })),
  );

  function openLightbox(index: number): void {
    setLightboxIndex(index);
    setLightboxOpen(true);
  }

  function openDetail(item: MediaItem): void {
    setDetailItem(item);
    setDrawerOpen(true);
  }

  function toggleSelectMode(): void {
    setSelectMode((on) => {
      if (on) view.clearSelection();
      return !on;
    });
  }

  /* ── Image mutations ─────────────────────────────────────────────────── */

  async function toggleFavorite(item: MediaItem): Promise<void> {
    try {
      await setFavorite(item.id, !item.favorite);
      refetchMedia(); // the reconciled mirror flips just this tile in place
    } catch {
      toast.error("Could not update favorite.");
    }
  }

  async function toggleKbExcluded(item: MediaItem): Promise<void> {
    const next = !item.kbExcluded;
    try {
      await setKbExcluded(item.id, next);
      refetchMedia();
      toast.success(
        next ? "Excluded from knowledge base." : "Included in knowledge base.",
      );
    } catch {
      toast.error("Could not update knowledge-base setting.");
    }
  }

  async function toggleAlbumMembership(
    item: MediaItem,
    albumId: string,
    member: boolean,
  ): Promise<void> {
    try {
      if (member) await addToAlbum(albumId, item.id);
      else await removeFromAlbum(albumId, item.id);
      refetchMedia();
      refetchAlbums();
      toast.success(member ? "Added to album." : "Removed from album.");
    } catch {
      toast.error("Could not update album membership.");
    }
  }

  async function handleDownload(item: MediaItem): Promise<void> {
    try {
      await downloadImage(item.id, item.title);
    } catch {
      toast.error("Download failed.");
    }
  }

  const deleteDetail =
    "This permanently deletes the image; it may also be attached to a chat message.";

  async function handleDelete(item: MediaItem): Promise<void> {
    const ok = await confirm({
      title: "Delete image?",
      detail: deleteDetail,
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteMedia(item.id);
      setDrawerOpen(false);
      refetchMedia();
      refetchAlbums();
      toast.success("Image deleted.");
    } catch {
      toast.error("Delete failed.");
    }
  }

  async function handleBulkDelete(): Promise<void> {
    const targets = view.selectedItems();
    if (!targets.length) return;
    const plural = targets.length > 1 ? "s" : "";
    const ok = await confirm({
      title: `Delete ${targets.length} image${plural}?`,
      detail: deleteDetail,
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    // allSettled, not all: one failed delete must not strand the rest (the grid would keep
    // showing already-deleted tiles, and a retry would 404 them). Always reconcile + report.
    const results = await Promise.allSettled(
      targets.map((t) => deleteMedia(t.id)),
    );
    view.clearSelection();
    refetchMedia();
    refetchAlbums();
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) {
      toast.error(
        `Deleted ${targets.length - failed} of ${targets.length}; ${failed} failed.`,
      );
    } else {
      toast.success(`Deleted ${targets.length} image${plural}.`);
    }
  }

  async function handleBulkAddToAlbum(album: Album): Promise<void> {
    const targets = view.selectedItems();
    if (!targets.length) return;
    const results = await Promise.allSettled(
      targets.map((t) => addToAlbum(album.id, t.id)),
    );
    view.clearSelection();
    refetchMedia();
    refetchAlbums();
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) {
      toast.error(
        `Added ${targets.length - failed} of ${targets.length} to ${album.name}; ${failed} failed.`,
      );
    } else {
      toast.success(`Added ${targets.length} to ${album.name}.`);
    }
  }

  /* ── Import ──────────────────────────────────────────────────────────── */

  let fileInput: HTMLInputElement | undefined;

  async function importFiles(files: File[]): Promise<void> {
    if (!files.length || importing()) return;
    setImporting(true);
    try {
      // allSettled so one rejected upload doesn't discard the ones that succeeded — the
      // gallery still refreshes to show them, and the toast reports the partial outcome.
      const results = await Promise.allSettled(
        files.map((f) => importImage(f)),
      );
      refetchMedia();
      refetchAlbums();
      const failed = results.filter((r) => r.status === "rejected").length;
      const ok = files.length - failed;
      if (failed && ok) {
        toast.warn(`Imported ${ok} of ${files.length}; ${failed} failed.`);
      } else if (failed) {
        toast.error("Import failed.");
      } else {
        const plural = ok > 1 ? "s" : "";
        toast.success(`Imported ${ok} image${plural} — gallery updated.`);
      }
    } finally {
      setImporting(false);
    }
  }

  /* ── Albums ──────────────────────────────────────────────────────────── */

  async function submitAlbumName(name: string): Promise<void> {
    const dialog = albumDialog();
    if (!dialog) return;
    try {
      if (dialog.mode === "create") {
        await createAlbum(name);
        toast.success(`Album "${name}" created.`);
      } else {
        await renameAlbum(dialog.album.id, name);
        toast.success("Album renamed.");
      }
      refetchAlbums();
    } catch {
      toast.error("Could not save album.");
    }
  }

  async function handleDeleteAlbum(album: Album): Promise<void> {
    const ok = await confirm({
      title: `Delete album "${album.name}"?`,
      detail: "The album is removed; the images in it are not deleted.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteAlbum(album.id);
      if (selectedAlbum() === album.id) setSelectedAlbum("all");
      refetchAlbums();
      refetchMedia();
      toast.success("Album deleted.");
    } catch {
      toast.error("Could not delete album.");
    }
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="GALLERY"
        subtitle="Images from chat attachments and knowledge-base uploads."
        assetId="ODY-GAL-01.0"
        actions={
          <Button
            variant="ghost"
            leading="upload"
            disabled={importing()}
            onClick={() => fileInput?.click()}
          >
            {importing() ? "IMPORTING…" : "IMPORT"}
          </Button>
        }
      />
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        multiple
        class="hidden"
        onChange={(e) => {
          const files = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = "";
          void importFiles(files);
        }}
      />

      <Show when={media()}>
        <InstrumentBand
          items={[
            { label: "TOTAL", value: String(items.length) },
            { label: "STORAGE", value: bytes(stats().bytes), tone: "info" },
            {
              label: "FAVORITES",
              value: String(stats().favorites),
              tone: "warn",
            },
            { label: "KB-EXCLUDED", value: String(stats().excluded) },
          ]}
        />
      </Show>

      <div class="flex gap-4 min-h-0">
        {/* Album sidebar */}
        <aside class="hidden w-44 shrink-0 lg:block">
          <Panel label="ALBUMS" flush>
            <Show
              when={!albums.error}
              fallback={
                <div class="p-3">
                  <ErrorState
                    message="ALBUMS UNAVAILABLE"
                    onRetry={refetchAlbums}
                  />
                </div>
              }
            >
              <Show
                when={albums.latest}
                fallback={
                  <div class="p-3">
                    <LoadingText />
                  </div>
                }
              >
                <For each={albumList()}>
                  {(album) => (
                    <div
                      class="flex items-stretch border-b border-line last:border-b-0"
                      classList={{ "bg-raised": selectedAlbum() === album.id }}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedAlbum(album.id)}
                        class="flex min-w-0 flex-1 items-center justify-between px-3 py-2 text-left transition-colors hover:bg-raised"
                      >
                        <Text
                          variant="label"
                          tone={selectedAlbum() === album.id ? "bright" : "dim"}
                          class="truncate min-w-0"
                        >
                          {album.name}
                        </Text>
                        <Text variant="micro" tone="dim" class="ml-2 shrink-0">
                          {album.count}
                        </Text>
                      </button>
                      <Show when={!album.system}>
                        <Menu
                          align="right"
                          trigger={
                            <span class="flex items-center px-2 text-dim transition-colors hover:text-bright">
                              <Icon name="menu" size={14} />
                            </span>
                          }
                          items={[
                            {
                              label: "RENAME",
                              icon: "edit",
                              onSelect: () =>
                                setAlbumDialog({ mode: "rename", album }),
                            },
                            {
                              label: "DELETE",
                              icon: "trash",
                              danger: true,
                              onSelect: () => void handleDeleteAlbum(album),
                            },
                          ]}
                        />
                      </Show>
                    </div>
                  )}
                </For>
                <button
                  type="button"
                  onClick={() => setAlbumDialog({ mode: "create" })}
                  class="flex w-full items-center gap-2 border-t border-line px-3 py-2 text-left transition-colors hover:bg-raised"
                >
                  <Icon name="plus" size={12} class="text-dim" />
                  <Text variant="label" tone="dim">
                    NEW ALBUM
                  </Text>
                </button>
              </Show>
            </Show>
          </Panel>
        </aside>

        {/* Grid */}
        <div class="flex-1 min-w-0">
          {/* Mobile album switch */}
          <Show when={albumList().length}>
            <Tabs
              class="mb-4 lg:hidden"
              items={albumList().map((a) => ({
                value: a.id,
                label: a.name,
              }))}
              value={selectedAlbum()}
              onChange={setSelectedAlbum}
            />
          </Show>

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
                    <Row gap={2}>
                      <Menu
                        align="right"
                        trigger={
                          <Button variant="default" size="sm" leading="library">
                            ADD TO ALBUM
                          </Button>
                        }
                        items={
                          customAlbums().length
                            ? customAlbums().map((a) => ({
                                label: a.name,
                                icon: "library" as const,
                                onSelect: () => void handleBulkAddToAlbum(a),
                              }))
                            : [
                                {
                                  label: "NO ALBUMS YET",
                                  onSelect: () => {},
                                  disabled: true,
                                },
                              ]
                        }
                      />
                      <Button
                        variant="danger"
                        size="sm"
                        leading="trash"
                        onClick={() => void handleBulkDelete()}
                      >
                        DELETE
                      </Button>
                    </Row>
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

            <Resource
              data={media}
              loadingLabel="LOADING MEDIA"
              onRetry={refetchMedia}
            >
              {() => (
                <Show
                  when={view.items().length}
                  fallback={
                    <EmptyState
                      icon="image"
                      message={view.isFiltered() ? "NO MATCHES" : "NO MEDIA"}
                      hint={
                        view.isFiltered()
                          ? "No media matches your search."
                          : "Attach images in chat or upload them to the knowledge base to populate the gallery."
                      }
                    />
                  }
                >
                  <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                    <For each={view.items()}>
                      {(item, i) => (
                        <MediaTile
                          item={item}
                          selectMode={selectMode()}
                          selected={
                            selectMode()
                              ? view.isSelected(item.id)
                              : detailItem()?.id === item.id
                          }
                          onSelect={() =>
                            selectMode()
                              ? view.toggleOne(item.id)
                              : openLightbox(i())
                          }
                          onToggleFavorite={() => void toggleFavorite(item)}
                          onOpenDetail={() => openDetail(item)}
                        />
                      )}
                    </For>
                  </div>
                </Show>
              )}
            </Resource>
          </Stack>
        </div>
      </div>

      <Lightbox
        items={lightboxItems()}
        index={lightboxIndex()}
        open={lightboxOpen()}
        onClose={() => setLightboxOpen(false)}
        onNavigate={setLightboxIndex}
      />

      <MediaDetailDrawer
        item={detailItem()}
        open={drawerOpen()}
        onClose={() => setDrawerOpen(false)}
        albums={customAlbums()}
        onToggleFavorite={(item) => void toggleFavorite(item)}
        onToggleKbExcluded={(item) => void toggleKbExcluded(item)}
        onToggleAlbum={(item, albumId, member) =>
          void toggleAlbumMembership(item, albumId, member)
        }
        onDownload={(item) => void handleDownload(item)}
        onDelete={(item) => void handleDelete(item)}
      />

      <AlbumNameDialog
        open={albumDialog() !== null}
        title={albumDialog()?.mode === "rename" ? "RENAME ALBUM" : "NEW ALBUM"}
        submitLabel={albumDialog()?.mode === "rename" ? "SAVE" : "CREATE"}
        initialName={
          albumDialog()?.mode === "rename"
            ? (albumDialog() as { album: Album }).album.name
            : ""
        }
        onClose={() => setAlbumDialog(null)}
        onSubmit={submitAlbumName}
      />
    </Stack>
  );
}
