import { createMemo, For, Show, type JSX } from "solid-js";
import {
  EmptyState,
  LoadingText,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Toggle,
  toast,
} from "~/ui";
import { setAgentToolEnabled, useAgentTools } from "../data";
import type { AgentTool } from "../model";

/** The agent's tool catalog, with a switch per tool (`AE-3.3`).
 *
 *  Presentation only: the catalog, each tool's description, and whether it is on all
 *  come from the backend, which derives them from the toolset registry the agent
 *  actually runs against — this panel never names a tool of its own. Grouped by
 *  category because that's how the catalog is organized and how an operator thinks
 *  about it ("turn off web", "turn off the shell"). */
export function AgentToolsPanel(): JSX.Element {
  const tools = useAgentTools();

  /** Category → its tools, in the order the backend listed them. */
  const grouped = createMemo(() => {
    const groups = new Map<string, AgentTool[]>();
    for (const tool of tools.latest ?? []) {
      const bucket = groups.get(tool.category);
      if (bucket) bucket.push(tool);
      else groups.set(tool.category, [tool]);
    }
    return [...groups.entries()];
  });

  const offCount = createMemo(
    () => (tools.latest ?? []).filter((t) => !t.enabled).length,
  );

  const toggle = async (tool: AgentTool) => {
    try {
      await setAgentToolEnabled(tool.name, !tool.enabled);
    } catch {
      toast.error(
        `Unable to ${tool.enabled ? "disable" : "enable"} ${tool.name}.`,
      );
    }
  };

  return (
    <Panel
      label="Agent tools"
      meta={
        <Show when={offCount()}>
          <StatusFlag status="warn">{`${offCount()} OFF`}</StatusFlag>
        </Show>
      }
    >
      <Show when={tools.latest} fallback={<LoadingText />}>
        <Show
          when={(tools.latest ?? []).length}
          fallback={<EmptyState icon="cpu" message="No tools registered" />}
        >
          <Stack gap={4}>
            <Text variant="micro" tone="dim">
              A tool switched off here is never offered to the agent and can
              never be invoked by it — on a live chat, on an unattended
              scheduled task, and on the resume of a run waiting for your
              approval alike.
            </Text>
            <For each={grouped()}>
              {([category, entries]) => (
                <Stack gap={3} class="pt-3">
                  <Text variant="label" tone="dim">
                    {category.toUpperCase()}
                  </Text>
                  <For each={entries}>
                    {(tool) => (
                      <Row align="center" justify="between" gap={4}>
                        <Stack gap={1}>
                          <Text variant="label" tone="default">
                            {tool.name}
                          </Text>
                          <Text variant="micro" tone="dim">
                            {tool.description}
                          </Text>
                        </Stack>
                        <Toggle
                          checked={tool.enabled}
                          onChange={() => void toggle(tool)}
                        />
                      </Row>
                    )}
                  </For>
                </Stack>
              )}
            </For>
          </Stack>
        </Show>
      </Show>
    </Panel>
  );
}
