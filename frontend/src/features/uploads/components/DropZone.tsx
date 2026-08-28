import { type JSX } from "solid-js";
import {
  Box,
  Button,
  cx,
  HIDDEN_FILE_INPUT,
  Icon,
  Stack,
  Text,
  useFileDrop,
} from "~/ui";

interface DropZoneProps {
  /** Hand the chosen/dropped files to the screen, which uploads them. */
  onFiles: (files: File[]) => void;
}

export function DropZone(props: DropZoneProps): JSX.Element {
  const drop = useFileDrop((files) => props.onFiles(files));

  return (
    <Box
      class={cx(
        "border-2 border-dashed flex flex-col items-center justify-center gap-3 p-8 text-center transition-colors",
        drop.isDragging()
          ? "border-info bg-info/10"
          : "border-line hover:border-dim hover:bg-raised",
      )}
      {...drop.dropHandlers}
    >
      <Icon
        name="upload"
        size={32}
        class={drop.isDragging() ? "text-info" : "text-dim"}
      />
      <Stack gap={1} class="items-center">
        <Text variant="label" tone={drop.isDragging() ? "info" : "dim"}>
          {drop.isDragging() ? "Drop to upload" : "Drop files here"}
        </Text>
        <Text variant="micro" tone="dim">
          PDF, image, and document formats accepted · max 50 MB
        </Text>
      </Stack>
      <input
        ref={drop.bindInput}
        {...HIDDEN_FILE_INPUT}
        {...drop.inputHandlers}
      />
      <Button variant="default" leading="upload" onClick={drop.openPicker}>
        Browse files
      </Button>
    </Box>
  );
}
