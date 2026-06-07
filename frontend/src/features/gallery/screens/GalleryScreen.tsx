import {
  createEffect,
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
  LoadingText,
  PageHeader,
  Panel,
  Stack,
  Tabs,
  Text,
  toast,
} from "~/ui";
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

  let seeded = false;
  createEffect(() => {
    const data = media();
    if (!seeded && data) {
      seeded = true;
      setItems(data.slice());
    }
  });

  const filtered = () => {
    const album = selectedAlbum();
    return album === "all" ? items() : items().filter((m) => m.album === album);
  };

  const totalImages = () => items().filter((m) => m.type === "image").length;
  const totalVideos = () => items().filter((m) => m.type === "video").length;
  const totalFavorites = () => items().filter((m) => m.favorite).length;

  function toggleFavorite(id: string) {
    setItems((prev) =>
      prev.map((m) => (m.id === id ? { ...m, favorite: !m.favorite } : m)),
    );
  }

  function openItem(item: MediaItem) {
    setSelectedItem(item);
    setDrawerOpen(true);
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
              { label: "IMAGES", value: String(totalImages()) },
              { label: "VIDEO", value: String(totalVideos()) },
              {
                label: "FAVORITES",
                value: String(totalFavorites()),
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

          <Suspense fallback={<LoadingText />}>
            <Show
              when={filtered().length}
              fallback={
                <EmptyState
                  icon="image"
                  message="NO MEDIA"
                  hint="Import files or generate with AI to populate the gallery."
                />
              }
            >
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                <For each={filtered()}>
                  {(item) => (
                    <MediaTile
                      item={item}
                      selected={selectedItem()?.id === item.id}
                      onSelect={() => openItem(item)}
                      onToggleFavorite={() => toggleFavorite(item.id)}
                    />
                  )}
                </For>
              </div>
            </Show>
          </Suspense>
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
