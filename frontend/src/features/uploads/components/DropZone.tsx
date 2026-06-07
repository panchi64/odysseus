import { type JSX } from "solid-js";
import { Box, Button, Icon, Stack, Text } from "~/ui";

interface DropZoneProps {
  onUpload?: () => void;
}

export function DropZone(props: DropZoneProps): JSX.Element {
  return (
    <Box class="border-2 border-dashed border-line flex flex-col items-center justify-center gap-3 p-8 text-center transition-colors hover:border-dim hover:bg-raised">
      <Icon name="upload" size={32} class="text-dim" />
      <Stack gap={1} class="items-center">
        <Text variant="label" tone="dim">
          DROP FILES HERE
        </Text>
        <Text variant="micro" tone="dim">
          PDF, image, and document formats accepted · max 50 MB
        </Text>
      </Stack>
      <Button variant="default" leading="upload" onClick={props.onUpload}>
        BROWSE FILES
      </Button>
    </Box>
  );
}
