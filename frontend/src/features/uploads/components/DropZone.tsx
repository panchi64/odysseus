import { createSignal, type JSX } from "solid-js";
import { Box, Button, cx, Icon, Stack, Text, toast, Tooltip } from "~/ui";
import { addMockUpload } from "../data";

interface DropZoneProps {
  onFileAdded?: (name: string) => void;
}

export function DropZone(props: DropZoneProps): JSX.Element {
  const [isDragging, setIsDragging] = createSignal(false);

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave() {
    setIsDragging(false);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length === 0) return;
    for (const file of files) {
      addMockUpload(file.name);
    }
    toast.success(
      files.length === 1
        ? `"${files[0].name}" queued for extraction`
        : `${files.length} files queued for extraction`,
    );
    props.onFileAdded?.(files[0]?.name ?? "");
  }

  return (
    <Box
      class={cx(
        "border-2 border-dashed flex flex-col items-center justify-center gap-3 p-8 text-center transition-colors",
        isDragging()
          ? "border-info bg-info/10"
          : "border-line hover:border-dim hover:bg-raised",
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <Icon
        name="upload"
        size={32}
        class={isDragging() ? "text-info" : "text-dim"}
      />
      <Stack gap={1} class="items-center">
        <Text variant="label" tone={isDragging() ? "info" : "dim"}>
          {isDragging() ? "DROP TO QUEUE" : "DROP FILES HERE"}
        </Text>
        <Text variant="micro" tone="dim">
          PDF, image, and document formats accepted · max 50 MB
        </Text>
      </Stack>
      <Tooltip label="File upload available in Phase 2" side="bottom">
        <Button variant="default" leading="upload" disabled>
          BROWSE FILES
        </Button>
      </Tooltip>
    </Box>
  );
}
