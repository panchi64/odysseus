import { type JSX } from "solid-js";
import { Stack } from "~/ui";
import { AgentToolsPanel } from "./AgentToolsPanel";
import { SearchProvidersPanel } from "./SearchProvidersPanel";

export function AgentToolsSection(): JSX.Element {
  return (
    <Stack gap={6}>
      <AgentToolsPanel />
      <SearchProvidersPanel />
    </Stack>
  );
}
