import { type JSX } from "solid-js";
import { Box, Icon, Menu, Row, Stack, Text } from "~/ui";
import { date } from "~/lib/format";
import type { Signature } from "../model";

interface SignatureTileProps {
  signature: Signature;
  onDelete: () => void;
}

export function SignatureTile(props: SignatureTileProps): JSX.Element {
  return (
    <div class="flex flex-col border border-line bg-surface p-3 gap-3 hover:border-dim hover:bg-raised transition-colors">
      {/* Signature art placeholder */}
      <Box class="aspect-video border border-line bg-bg flex items-center justify-center gap-3">
        <Icon name="pen" size={20} class="text-dim" />
        <Text variant="readout" tone="dim" class="font-mono italic select-none">
          {props.signature.name.split("/")[0].trim()}
        </Text>
      </Box>

      <Row align="center" justify="between" gap={2}>
        <Stack gap={0}>
          <Text variant="label" tone="bright">
            {props.signature.name}
          </Text>
          <Row gap={2}>
            <Text variant="micro" tone="dim">
              CREATED {date(props.signature.createdAt)}
            </Text>
            <Text variant="micro" tone="dim">
              · USED {props.signature.usedCount}×
            </Text>
          </Row>
        </Stack>
        <Menu
          trigger={
            <button
              type="button"
              class="text-dim hover:text-bright transition-colors p-1"
            >
              <Icon name="menu" size={14} />
            </button>
          }
          items={[
            { label: "Insert into PDF", icon: "file", onSelect: () => {} },
            { label: "Insert into Email", icon: "mail", onSelect: () => {} },
            {
              label: "Delete",
              icon: "trash",
              onSelect: props.onDelete,
              danger: true,
            },
          ]}
          align="right"
        />
      </Row>
    </div>
  );
}
