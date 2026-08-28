import { type JSX } from "solid-js";
import { PageHeader, Stack } from "~/ui";

/** Chrome shared by every settings section. The rail lists the sections, so this
 *  holds no tab state. */
export function SettingsLayout(props: { children: JSX.Element }): JSX.Element {
  return (
    <Stack gap={6}>
      <PageHeader
        title="SETTINGS"
        subtitle="Appearance, chat, agent-tool, and offline configuration."
        assetId="ODY-CFG-03.0"
      />
      {props.children}
    </Stack>
  );
}
