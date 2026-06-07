import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  EmptyState,
  Input,
  ListRow,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Toggle,
  type Status,
} from "~/ui";
import { useMcpServers } from "../data";
import type { McpServer, McpStatus } from "../model";

const mcpStatusFlag: Record<McpStatus, Status> = {
  connected: "nominal",
  error: "alert",
  disconnected: "idle",
};

function ServerCard(props: {
  server: McpServer;
  onToggleTool: (serverId: string, toolName: string, enabled: boolean) => void;
}): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const enabledCount = () => props.server.tools.filter((t) => t.enabled).length;

  return (
    <Panel
      label={props.server.name}
      state={props.server.status === "error" ? "alert" : "default"}
      meta={
        <Row gap={2} align="center">
          <Show when={props.server.authRequired}>
            <StatusFlag status="info">AUTH</StatusFlag>
          </Show>
          <StatusFlag status={mcpStatusFlag[props.server.status]}>
            {props.server.status.toUpperCase()}
          </StatusFlag>
          <Button
            size="sm"
            variant="ghost"
            trailing={expanded() ? "chevron-down" : "chevron-right"}
            onClick={() => setExpanded((v) => !v)}
          >
            {props.server.tools.length} TOOLS
          </Button>
        </Row>
      }
      flush={expanded()}
    >
      <Show when={!expanded()}>
        <Stack gap={2}>
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              TRANSPORT
            </Text>
            <Text variant="micro" tone="bright">
              {props.server.transport.toUpperCase()}
            </Text>
          </Row>
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              ENDPOINT
            </Text>
            <Text variant="micro" tone="bright">
              {props.server.url}
            </Text>
          </Row>
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              TOOLS ENABLED
            </Text>
            <Text variant="micro" tone="nominal">
              {enabledCount()} / {props.server.tools.length}
            </Text>
          </Row>
        </Stack>
      </Show>

      <Show when={expanded()}>
        <For each={props.server.tools}>
          {(tool) => (
            <ListRow
              label={tool.name}
              leading="code"
              right={
                <Row gap={2} align="center">
                  <Text variant="micro" tone="dim" class="max-w-xs truncate">
                    {tool.description}
                  </Text>
                  <Toggle
                    checked={tool.enabled}
                    onChange={(v) =>
                      props.onToggleTool(props.server.id, tool.name, v)
                    }
                  />
                </Row>
              }
            />
          )}
        </For>
        <div class="px-3 py-2">
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              TRANSPORT
            </Text>
            <Text variant="micro" tone="bright">
              {props.server.transport.toUpperCase()}
            </Text>
            <Text variant="micro" tone="dim">
              ·
            </Text>
            <Text variant="micro" tone="bright">
              {props.server.url}
            </Text>
          </Row>
        </div>
      </Show>
    </Panel>
  );
}

export function McpScreen(): JSX.Element {
  const serverResource = useMcpServers();
  const [servers, setServers] = createStore<McpServer[]>([]);
  const [seeded, setSeeded] = createSignal(false);
  const [registerOpen, setRegisterOpen] = createSignal(false);
  const [regName, setRegName] = createSignal("");
  const [regUrl, setRegUrl] = createSignal("");
  const [regCommand, setRegCommand] = createSignal("");

  // seed store once from resource
  const resolvedServers = () => {
    const data = serverResource();
    if (data && !seeded()) {
      setSeeded(true);
      setServers(
        data.map((s) => ({ ...s, tools: s.tools.map((t) => ({ ...t })) })),
      );
    }
    return data;
  };

  function toggleTool(serverId: string, toolName: string, enabled: boolean) {
    setServers(
      produce((s) => {
        const srv = s.find((x) => x.id === serverId);
        const tool = srv?.tools.find((t) => t.name === toolName);
        if (tool) tool.enabled = enabled;
      }),
    );
  }

  function registerServer() {
    if (!regName().trim()) return;
    setServers(
      produce((s) =>
        s.push({
          id: `mcp-custom-${Date.now()}`,
          name: regName(),
          transport: regUrl() ? "http" : "stdio",
          url: regUrl() || regCommand(),
          status: "disconnected",
          tools: [],
        }),
      ),
    );
    setRegName("");
    setRegUrl("");
    setRegCommand("");
    setRegisterOpen(false);
  }

  const connectedCount = () =>
    servers.filter((s) => s.status === "connected").length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="MCP CONNECTIONS"
        subtitle="Model Context Protocol server registration and tool management."
        assetId="SYS-MCP-04.1"
        actions={
          <Row gap={2} align="center">
            <StatusFlag
              status="nominal"
              dot
            >{`${connectedCount()} CONNECTED`}</StatusFlag>
            <Button
              variant="default"
              leading="plus"
              onClick={() => setRegisterOpen(true)}
            >
              REGISTER
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING SERVERS" />}>
        <Show when={resolvedServers()}>
          <Show
            when={servers.length}
            fallback={
              <EmptyState
                icon="plug"
                message="NO SERVERS"
                hint="Register an MCP server to expose tools to the agent."
                action={
                  <Button onClick={() => setRegisterOpen(true)} leading="plus">
                    REGISTER SERVER
                  </Button>
                }
              />
            }
          >
            <Stack gap={4}>
              <For each={servers}>
                {(srv) => <ServerCard server={srv} onToggleTool={toggleTool} />}
              </For>
            </Stack>
          </Show>
        </Show>
      </Suspense>

      <Modal
        open={registerOpen()}
        onClose={() => setRegisterOpen(false)}
        title="REGISTER MCP SERVER"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setRegisterOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={registerServer}
              disabled={!regName().trim()}
            >
              REGISTER
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="SERVER NAME"
            value={regName()}
            onInput={(e) => setRegName(e.currentTarget.value)}
            placeholder="e.g. My Custom MCP"
          />
          <Input
            label="COMMAND (stdio)"
            value={regCommand()}
            onInput={(e) => setRegCommand(e.currentTarget.value)}
            placeholder="e.g. npx -y @modelcontextprotocol/server-name"
          />
          <Input
            label="URL (http transport)"
            value={regUrl()}
            onInput={(e) => setRegUrl(e.currentTarget.value)}
            placeholder="e.g. http://localhost:8080/mcp"
          />
          <Text variant="micro" tone="dim">
            Auth tokens are stored encrypted at rest. Provide credentials after
            registration via the server detail panel.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
