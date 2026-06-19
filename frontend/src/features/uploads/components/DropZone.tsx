import { createSignal, type JSX } from "solid-js";
import { Box, Button, cx, Icon, Stack, Text } from "~/ui";

interface DropZoneProps {
  /** Hand the chosen/dropped files to the screen, which uploads them. */
  onFiles: (files: File[]) => void;
}

export function DropZone(props: DropZoneProps): JSX.Element {
  const [isDragging, setIsDragging] = createSignal(false);
  let input: HTMLInputElement | undefined;

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
    if (files.length) props.onFiles(files);
  }

  function handlePick(e: Event) {
    const target = e.currentTarget as HTMLInputElement;
    const files = Array.from(target.files ?? []);
    if (files.length) props.onFiles(files);
    target.value = ""; // allow re-picking the same file
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
          {isDragging() ? "DROP TO UPLOAD" : "DROP FILES HERE"}
        </Text>
        <Text variant="micro" tone="dim">
          PDF, image, and document formats accepted · max 50 MB
        </Text>
      </Stack>
      <input
        ref={input}
        type="file"
        multiple
        class="hidden"
        onChange={handlePick}
      />
      <Button variant="default" leading="upload" onClick={() => input?.click()}>
        BROWSE FILES
      </Button>
    </Box>
  );
}
