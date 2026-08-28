import { For, Show, type JSX } from "solid-js";
import {
  Button,
  Divider,
  Drawer,
  Field,
  ImageFrame,
  Row,
  Stack,
  StatusFlag,
  Text,
  Toggle,
} from "~/ui";
import { useAuthedBlobUrl } from "~/lib/api";
import { bytes, date } from "~/lib/format";
import type { Album, MediaItem } from "../model";
import { fullImagePath } from "../data";

interface MediaDetailDrawerProps {
  item: MediaItem | null;
  open: boolean;
  onClose: () => void;
  /** Custom albums only (system buckets aren't user-assignable). */
  albums: Album[];
  onToggleFavorite: (item: MediaItem) => void;
  onToggleKbExcluded: (item: MediaItem) => void;
  /** Add to / remove from a custom album (member = the desired next state). */
  onToggleAlbum: (item: MediaItem, albumId: string, member: boolean) => void;
  onDownload: (item: MediaItem) => void;
  onDelete: (item: MediaItem) => void;
}

export function MediaDetailDrawer(props: MediaDetailDrawerProps): JSX.Element {
  // Resolve the full image only while the drawer is open and an item is set.
  const preview = useAuthedBlobUrl(() =>
    props.open && props.item ? fullImagePath(props.item.id) : undefined,
  );

  return (
    <Drawer
      open={props.open}
      onClose={props.onClose}
      title="Media detail"
      side="right"
    >
      <Show
        when={props.item}
        fallback={<Text tone="dim">No item selected.</Text>}
      >
        {(item) => (
          <Stack gap={4}>
            <ImageFrame
              src={preview()}
              error={preview.error !== undefined}
              alt={item().title}
              fit="contain"
              class="aspect-square w-full"
            />

            <Stack gap={2}>
              <Text variant="label" tone="bright">
                {item().title}
              </Text>
              <Row gap={2} wrap>
                <StatusFlag status="nominal">Image</StatusFlag>
                <Show when={item().favorite}>
                  <StatusFlag status="warn">Favorite</StatusFlag>
                </Show>
                <Show when={item().kbExcluded}>
                  <StatusFlag>KB-excluded</StatusFlag>
                </Show>
              </Row>
            </Stack>

            <Stack gap={1}>
              <Field
                label="Size"
                value={bytes(item().sizeBytes)}
                orientation="row"
              />
              <Field
                label="Created"
                value={date(item().createdAt)}
                orientation="row"
              />
            </Stack>

            <Divider />

            {/* Flags */}
            <Stack gap={2}>
              <Row align="center" justify="between" gap={2}>
                <Text variant="label" tone="dim">
                  Favorite
                </Text>
                <Toggle
                  checked={item().favorite}
                  onChange={() => props.onToggleFavorite(item())}
                />
              </Row>
              <Row align="center" justify="between" gap={2}>
                <Stack gap={1} class="min-w-0">
                  <Text variant="label" tone="dim">
                    Exclude from KB
                  </Text>
                  <Text variant="micro" tone="dim">
                    Keep this image out of the retrieval corpus.
                  </Text>
                </Stack>
                <Toggle
                  checked={item().kbExcluded}
                  onChange={() => props.onToggleKbExcluded(item())}
                />
              </Row>
            </Stack>

            <Divider />

            {/* Album membership */}
            <Stack gap={2}>
              <Text variant="label" tone="dim">
                Albums
              </Text>
              <Show
                when={props.albums.length}
                fallback={
                  <Text variant="micro" tone="dim">
                    No albums yet — create one from the gallery sidebar.
                  </Text>
                }
              >
                <Stack gap={1}>
                  <For each={props.albums}>
                    {(album) => {
                      const member = (): boolean =>
                        item().albumIds.includes(album.id);
                      return (
                        <Row align="center" justify="between" gap={2}>
                          <Text
                            variant="label"
                            tone={member() ? "bright" : "dim"}
                            class="truncate min-w-0"
                          >
                            {album.name}
                          </Text>
                          <Toggle
                            checked={member()}
                            onChange={(next) =>
                              props.onToggleAlbum(item(), album.id, next)
                            }
                          />
                        </Row>
                      );
                    }}
                  </For>
                </Stack>
              </Show>
            </Stack>

            <Divider />

            {/* Actions */}
            <Row gap={2} wrap>
              <Button
                variant="default"
                size="sm"
                leading="download"
                onClick={() => props.onDownload(item())}
              >
                Download
              </Button>
              <Button
                variant="danger"
                size="sm"
                leading="trash"
                onClick={() => props.onDelete(item())}
              >
                Delete
              </Button>
            </Row>
          </Stack>
        )}
      </Show>
    </Drawer>
  );
}
