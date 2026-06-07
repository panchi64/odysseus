import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Drawer,
  EmptyState,
  Input,
  ListRow,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
  Toggle,
  Tooltip,
  toast,
  type Status,
} from "~/ui";
import { useMcpServers } from "../data";
import type { McpAuthCredentials, McpServer, McpStatus } from "../model";

const mcpStatusFlag: Record<McpStatus, Status> = {
  connected: "nominal",
  error: "alert",
  disconnected: "idle",
};

/** Format ISO timestamp to a short readable label. */
function formatErrorTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Auth Drawer
// ---------------------------------------------------------------------------

interface AuthDrawerProps {
  server: McpServer | null;
  onClose: () => void;
  onSave: (serverId: string, creds: McpAuthCredentials) => void;
}

function AuthDrawer(props: AuthDrawerProps): JSX.Element {
  const [method, setMethod] =
    createSignal<McpAuthCredentials["method"]>("api_key");
  const [token, setToken] = createSignal("");
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");

  const handleSave = () => {
    if (!props.server) return;

    const creds: McpAuthCredentials = { method: method() };
    if (method() === "api_key" || method() === "bearer") {
      if (!token().trim()) {
        toast.error("Token is required.");
        return;
      }
      creds.token = token().trim();
    } else {
      if (!username().trim() || !password().trim()) {
        toast.error("Username and password are required.");
        return;
      }
      creds.username = username().trim();
      creds.password = password().trim();
    }

    props.onSave(props.server.id, creds);
    toast.success(`Auth configured for "${props.server.name}".`);
    props.onClose();
  };

  // Reset fields when the drawer opens for a (potentially different) server
  const existing = () => props.server?.credentials;
  const open = () => props.server !== null;

  // Populate from existing creds when the drawer opens
  const effectiveMethod = () => existing()?.method ?? "api_key";

  return (
    <Drawer
      open={open()}
      onClose={props.onClose}
      title="CONFIGURE AUTH"
      footer={
        <Row gap={2}>
          <Button variant="ghost" onClick={props.onClose}>
            CANCEL
          </Button>
          <Button variant="primary" onClick={handleSave}>
            SAVE CREDENTIALS
          </Button>
        </Row>
      }
    >
      <Show when={props.server}>
        {(srv) => (
          <Stack gap={4}>
            <Text variant="micro" tone="dim">
              Credentials are stored encrypted at rest. Server:{" "}
              <span class="text-bright">{srv().name}</span>
            </Text>

            <Select
              label="AUTH METHOD"
              value={effectiveMethod()}
              onChange={(v) => setMethod(v as McpAuthCredentials["method"])}
              options={[
                { value: "api_key", label: "API KEY" },
                { value: "bearer", label: "BEARER TOKEN" },
                { value: "basic", label: "BASIC (USER / PASS)" },
              ]}
            />

            <Show
              when={
                effectiveMethod() === "api_key" ||
                effectiveMethod() === "bearer"
              }
            >
              <Input
                label={effectiveMethod() === "api_key" ? "API KEY" : "TOKEN"}
                type="password"
                value={existing()?.token ?? token()}
                onInput={(e) => setToken(e.currentTarget.value)}
                placeholder="Paste your key here"
              />
            </Show>

            <Show when={effectiveMethod() === "basic"}>
              <Input
                label="USERNAME"
                value={existing()?.username ?? username()}
                onInput={(e) => setUsername(e.currentTarget.value)}
                placeholder="e.g. admin"
              />
              <Input
                label="PASSWORD"
                type="password"
                value={existing()?.password ?? password()}
                onInput={(e) => setPassword(e.currentTarget.value)}
                placeholder="••••••••"
              />
            </Show>
          </Stack>
        )}
      </Show>
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Server Card
// ---------------------------------------------------------------------------

function ServerCard(props: {
  server: McpServer;
  onToggleTool: (serverId: string, toolName: string, enabled: boolean) => void;
  onRetry: (serverId: string) => void;
  onConfigureAuth: (server: McpServer) => void;
}): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const enabledCount = () => props.server.tools.filter((t) => t.enabled).length;

  const isError = () => props.server.status === "error";
  const isDisconnected = () => props.server.status === "disconnected";
  const needsAttention = () => isError() || isDisconnected();

  const errorTooltip = () => {
    const msg = props.server.errorMessage ?? "Unknown error";
    const at = props.server.errorAt
      ? ` — ${formatErrorTime(props.server.errorAt)}`
      : "";
    return `${msg}${at}`;
  };

  return (
    <Panel
      label={props.server.name}
      state={isError() ? "alert" : "default"}
      meta={
        <Row gap={2} align="center">
          <Show when={props.server.authRequired}>
            <StatusFlag status="info">AUTH</StatusFlag>
          </Show>

          {/* Error status with tooltip showing diagnostics */}
          <Show
            when={isError()}
            fallback={
              <StatusFlag status={mcpStatusFlag[props.server.status]}>
                {props.server.status.toUpperCase()}
              </StatusFlag>
            }
          >
            <Tooltip label={errorTooltip()} side="left">
              <StatusFlag status="alert">ERROR</StatusFlag>
            </Tooltip>
          </Show>

          {/* Retry button for error or disconnected servers */}
          <Show when={needsAttention()}>
            <Button
              size="sm"
              variant="ghost"
              leading="refresh"
              onClick={() => props.onRetry(props.server.id)}
            >
              RETRY
            </Button>
          </Show>

          {/* Configure auth button for auth-required servers */}
          <Show when={props.server.authRequired}>
            <Button
              size="sm"
              variant="ghost"
              leading="key"
              onClick={() => props.onConfigureAuth(props.server)}
            >
              {props.server.credentials ? "UPDATE AUTH" : "CONFIGURE AUTH"}
            </Button>
          </Show>

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

          {/* Inline error detail for error-state servers */}
          <Show when={isError() && props.server.errorMessage}>
            <Row gap={2} align="center">
              <Text variant="micro" tone="dim">
                LAST ERROR
              </Text>
              <Text variant="micro" tone="alert">
                {props.server.errorMessage}
              </Text>
            </Row>
          </Show>
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

// ---------------------------------------------------------------------------
// McpScreen
// ---------------------------------------------------------------------------

export function McpScreen(): JSX.Element {
  const serverResource = useMcpServers();
  const [servers, setServers] = createStore<McpServer[]>([]);
  const [seeded, setSeeded] = createSignal(false);
  const [registerOpen, setRegisterOpen] = createSignal(false);
  const [regName, setRegName] = createSignal("");
  const [regUrl, setRegUrl] = createSignal("");
  const [regCommand, setRegCommand] = createSignal("");
  const [authTarget, setAuthTarget] = createSignal<McpServer | null>(null);

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

  function retryConnection(serverId: string) {
    const srv = servers.find((s) => s.id === serverId);
    if (!srv) return;

    // Optimistically move to connecting (disconnected) and surface feedback
    setServers(
      produce((s) => {
        const target = s.find((x) => x.id === serverId);
        if (target) {
          target.status = "disconnected";
          target.errorMessage = undefined;
          target.errorAt = undefined;
        }
      }),
    );

    toast.info(`Retrying connection to "${srv.name}"…`);

    // Simulate async connection attempt — in Phase 2 this calls the API
    setTimeout(() => {
      setServers(
        produce((s) => {
          const target = s.find((x) => x.id === serverId);
          if (target) {
            // Mock: stays in error for servers that were already errored
            target.status = "error";
            target.errorMessage =
              "Connection refused — server not reachable at " + target.url;
            target.errorAt = new Date().toISOString();
          }
        }),
      );
      toast.error(`Could not connect to "${srv.name}". Check the server logs.`);
    }, 2000);
  }

  function saveCredentials(serverId: string, creds: McpAuthCredentials) {
    setServers(
      produce((s) => {
        const target = s.find((x) => x.id === serverId);
        if (target) target.credentials = creds;
      }),
    );
  }

  function registerServer() {
    if (!regName().trim()) return;

    const name = regName().trim();
    const newServer: McpServer = {
      id: `mcp-custom-${Date.now()}`,
      name,
      transport: regUrl() ? "http" : "stdio",
      url: regUrl() || regCommand(),
      status: "disconnected",
      tools: [],
    };

    setServers(produce((s) => s.push(newServer)));
    setRegName("");
    setRegUrl("");
    setRegCommand("");
    setRegisterOpen(false);

    toast.success(`"${name}" registered. Attempting connection…`);

    // Simulate connection attempt in Phase 1
    setTimeout(() => {
      setServers(
        produce((s) => {
          const target = s.find((x) => x.id === newServer.id);
          if (target) {
            target.status = "error";
            target.errorMessage =
              "Could not reach server — verify the command or URL and retry.";
            target.errorAt = new Date().toISOString();
          }
        }),
      );
      toast.error(
        `Could not connect to "${name}". Use RETRY once the server is running.`,
      );
    }, 3000);
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
                {(srv) => (
                  <ServerCard
                    server={srv}
                    onToggleTool={toggleTool}
                    onRetry={retryConnection}
                    onConfigureAuth={(s) => setAuthTarget(s)}
                  />
                )}
              </For>
            </Stack>
          </Show>
        </Show>
      </Suspense>

      {/* Register modal */}
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
            After registration the system will attempt to connect automatically.
            For auth-required servers, use CONFIGURE AUTH on the server card.
          </Text>
        </Stack>
      </Modal>

      {/* Auth credentials drawer */}
      <AuthDrawer
        server={authTarget()}
        onClose={() => setAuthTarget(null)}
        onSave={saveCredentials}
      />
    </Stack>
  );
}
