import { For, type JSX } from "solid-js";
import { Box, Button, Icon, Row, Stack, Text } from "~/ui";
import { bytes } from "~/lib/format";
import type { MediaItem } from "../model";

interface MediaTileProps {
  item: MediaItem;
  selected?: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
}

export function MediaTile(props: MediaTileProps): JSX.Element {
  return (
    <div
      class="group relative flex flex-col gap-2 border border-line bg-surface p-2 transition-colors hover:border-dim hover:bg-raised cursor-pointer"
      classList={{ "border-bright bg-raised": props.selected }}
      onClick={props.onSelect}
    >
      {/* Placeholder tile */}
      <Box class="aspect-square w-full border border-line bg-bg flex items-center justify-center">
        <Icon
          name={props.item.type === "video" ? "play" : "image"}
          size={28}
          class="text-dim"
        />
      </Box>

      <Stack gap={1}>
        <Row align="center" justify="between" gap={1}>
          <Text variant="micro" tone="bright" class="truncate min-w-0 flex-1">
            {props.item.title}
          </Text>
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              props.onToggleFavorite();
            }}
            leading={props.item.favorite ? "dot" : "dot"}
            class={props.item.favorite ? "text-warn" : "text-dim"}
          />
        </Row>
        <Row gap={1} wrap>
          <For each={props.item.tags.slice(0, 2)}>
            {(tag) => (
              <Text variant="micro" tone="dim" class="border border-line px-1">
                {tag}
              </Text>
            )}
          </For>
        </Row>
        <Text variant="micro" tone="dim">
          {bytes(props.item.sizeBytes)}
        </Text>
      </Stack>
    </div>
  );
}
