import { Show, type JSX } from "solid-js";
import { Button, Icon, ImageFrame, Row, Stack, Text } from "~/ui";
import { useAuthedBlobUrl } from "~/lib/api";
import { bytes, relativeTime } from "~/lib/format";
import type { MediaItem } from "../model";
import { thumbnailPath } from "../data";

interface MediaTileProps {
  item: MediaItem;
  selected?: boolean;
  /** When true, the tile renders a selection checkbox and the whole tile toggles
   *  selection instead of opening the viewer. */
  selectMode?: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
  /** Open the detail drawer (per-image controls) — hidden in select mode. */
  onOpenDetail: () => void;
}

export function MediaTile(props: MediaTileProps): JSX.Element {
  const thumb = useAuthedBlobUrl(() => thumbnailPath(props.item.id));

  return (
    <div
      class="group relative flex cursor-pointer flex-col gap-2 rounded-panel bg-surface p-2 shadow-1 transition-colors hover:bg-raised"
      classList={{ "bg-raised": props.selected }}
      onClick={props.onSelect}
    >
      <div class="relative">
        <ImageFrame
          src={thumb()}
          error={thumb.error !== undefined}
          alt={props.item.title}
          fit="cover"
          class="aspect-square w-full"
        />
        <Show when={props.selectMode}>
          <span
            class="absolute left-1.5 top-1.5 flex size-4 items-center justify-center rounded-ctl border bg-bg"
            classList={{
              "border-bright text-bright": props.selected,
              "border-line text-transparent": !props.selected,
            }}
            aria-hidden="true"
          >
            <Show when={props.selected}>
              <Icon name="check" size={12} />
            </Show>
          </span>
        </Show>
      </div>

      <Stack gap={1}>
        <Row align="center" justify="between" gap={1}>
          <Text variant="micro" tone="bright" class="truncate min-w-0 flex-1">
            {props.item.title}
          </Text>
          <Show when={!props.selectMode}>
            <Button
              variant="ghost"
              size="sm"
              aria-label={props.item.favorite ? "Unfavorite" : "Favorite"}
              onClick={(e) => {
                e.stopPropagation();
                props.onToggleFavorite();
              }}
              leading="dot"
              class={props.item.favorite ? "text-warn" : "text-dim"}
            />
            <Button
              variant="ghost"
              size="sm"
              aria-label="Details"
              onClick={(e) => {
                e.stopPropagation();
                props.onOpenDetail();
              }}
              leading="settings"
              class="text-dim"
            />
          </Show>
        </Row>
        <Row align="center" justify="between" gap={1}>
          <Text variant="micro" tone="dim">
            {bytes(props.item.sizeBytes)}
          </Text>
          <Text variant="micro" tone="dim">
            {relativeTime(props.item.createdAt)}
          </Text>
        </Row>
      </Stack>
    </div>
  );
}
