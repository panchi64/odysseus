import { type JSX } from "solid-js";
import { Panel, Row, Stack, Text, ThemeToggle } from "~/ui";

export function AppearanceSection(): JSX.Element {
  return (
    <Panel label="APPEARANCE">
      <Row align="center" justify="between">
        <Stack gap={1}>
          <Text variant="label" tone="default">
            THEME
          </Text>
          <Text variant="micro" tone="dim">
            Phosphor (dark), Paper (light), or follow system. Stored locally on
            this device.
          </Text>
        </Stack>
        <ThemeToggle />
      </Row>
    </Panel>
  );
}
