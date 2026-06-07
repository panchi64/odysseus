import { createSignal, type JSX } from "solid-js";
import { Box, Button, Input, Modal, Row, Stack, Text } from "~/ui";

interface DrawSignatureModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (name: string) => void;
}

export function DrawSignatureModal(
  props: DrawSignatureModalProps,
): JSX.Element {
  const [name, setName] = createSignal("");
  const [hasDrawn, setHasDrawn] = createSignal(false);

  function handleSave() {
    if (!name().trim()) return;
    props.onSave(name().trim());
    setName("");
    setHasDrawn(false);
    props.onClose();
  }

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title="DRAW NEW SIGNATURE"
      class="max-w-lg"
      footer={
        <Row gap={2}>
          <Button variant="ghost" onClick={props.onClose}>
            CANCEL
          </Button>
          <Button
            variant="primary"
            leading="check"
            disabled={!hasDrawn() || !name().trim()}
            onClick={handleSave}
          >
            SAVE SIGNATURE
          </Button>
        </Row>
      }
    >
      <Stack gap={4}>
        <Input
          label="SIGNATURE NAME"
          placeholder="e.g. Primary / Legal"
          value={name()}
          onInput={(e) => setName(e.currentTarget.value)}
        />

        {/* Drawing area placeholder */}
        <Stack gap={1}>
          <Text variant="label" tone="dim">
            DRAWING AREA
          </Text>
          <Box
            class="border-2 border-dashed border-line bg-bg flex items-center justify-center cursor-crosshair transition-colors hover:border-dim"
            style={{ height: "140px" }}
            onClick={() => setHasDrawn(true)}
          >
            {hasDrawn() ? (
              <Text
                variant="readout"
                tone="dim"
                class="font-mono italic select-none"
              >
                {name() || "Signature"}
              </Text>
            ) : (
              <Text variant="micro" tone="dim">
                Click or draw here to sign
              </Text>
            )}
          </Box>
          <Text variant="micro" tone="dim">
            Real drawing canvas in Phase 2. Click the area to simulate a mark.
          </Text>
        </Stack>

        <Row gap={2} justify="end">
          <Button
            variant="ghost"
            size="sm"
            leading="refresh"
            onClick={() => setHasDrawn(false)}
          >
            CLEAR
          </Button>
        </Row>
      </Stack>
    </Modal>
  );
}
