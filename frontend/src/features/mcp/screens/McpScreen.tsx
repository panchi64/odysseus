import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  confirm,
  Drawer,
  EmptyState,
  ExpandableText,
  InfoHint,
  Input,
  ListRow,
  ListToolbar,
  LoadingText,
  Menu,
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
import { createListView } from "~/lib/list";
import {
  connectMcpServer,
  deleteMcpServer,
  mcpErrorMessage,
  registerMcpServer,
  setMcpCredentials,
  setMcpToolPolicy,
  useMcpServers,
} from "../data";
import type {
  McpAuthCredentials,
  McpServer,
  McpStatus,
  McpTransport,
} from "../model";

const TRANSPORT_HINT =
  "STDIO runs the server as a local subprocess and talks over stdin/stdout — best for tools on this machine. HTTP connects to a server over the network at a URL — use it for remote or shared servers. SSE is the older network transport, for servers that predate Streamable HTTP.";

const TRUST_HINT =
  "An external tool's effects aren't knowable to Odysseus, so every call pauses for your approval by default. Trust one you've vetted to let it run without asking — one tool at a time, and revocable at any moment.";

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
    props.onClose();
  };

  const open = () => props.server !== null;

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
              Credentials are stored encrypted at rest and never read back —
              saving replaces what is stored. Server:{" "}
              <span class="text-bright">{srv().name}</span>
            </Text>

            <Select
              label="AUTH METHOD"
              value={method()}
              onChange={(v) => setMethod(v as McpAuthCredentials["method"])}
              options={[
                { value: "api_key", label: "API KEY" },
                { value: "bearer", label: "BEARER TOKEN" },
                { value: "basic", label: "BASIC (USER / PASS)" },
              ]}
            />

            <Show when={method() === "api_key" || method() === "bearer"}>
              <Input
                label={method() === "api_key" ? "API KEY" : "TOKEN"}
                type="password"
                value={token()}
                onInput={(e) => setToken(e.currentTarget.value)}
                placeholder="Paste your key here"
              />
            </Show>

            <Show when={method() === "basic"}>
              <Input
                label="USERNAME"
                value={username()}
                onInput={(e) => setUsername(e.currentTarget.value)}
                placeholder="e.g. admin"
              />
              <Input
                label="PASSWORD"
                type="password"
                value={password()}
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
  busy: boolean;
  onSetToolPolicy: (
    serverId: string,
    toolName: string,
    patch: { enabled?: boolean; trusted?: boolean },
  ) => void;
  onRetry: (server: McpServer) => void;
  onConfigureAuth: (server: McpServer) => void;
  onDelete: (server: McpServer) => void;
}): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const enabledCount = () => props.server.tools.filter((t) => t.enabled).length;
  const trustedCount = () => props.server.tools.filter((t) => t.trusted).length;
  const hasTools = () => props.server.tools.length > 0;

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
              disabled={props.busy}
              onClick={() => props.onRetry(props.server)}
            >
              {props.busy ? "CONNECTING…" : "RETRY"}
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
              {props.server.hasCredentials ? "UPDATE AUTH" : "CONFIGURE AUTH"}
            </Button>
          </Show>

          <Show
            when={hasTools()}
            fallback={
              <Tooltip label="This server exposes no tools to the agent.">
                <Button size="sm" variant="ghost" disabled>
                  0 TOOLS
                </Button>
              </Tooltip>
            }
          >
            <Button
              size="sm"
              variant="ghost"
              trailing={expanded() ? "chevron-down" : "chevron-right"}
              onClick={() => setExpanded((v) => !v)}
            >
              {props.server.tools.length} TOOLS
            </Button>
          </Show>

          <Menu
            trigger={
              <span class="px-1 text-dim hover:text-bright">
                <Text variant="micro">···</Text>
              </span>
            }
            items={[
              {
                label: "DELETE SERVER",
                icon: "trash",
                danger: true,
                onSelect: () => props.onDelete(props.server),
              },
            ]}
          />
        </Row>
      }
      flush={expanded() && hasTools()}
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
            <InfoHint label={TRANSPORT_HINT} size={12} />
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
            <Text variant="micro" tone="dim">
              ·
            </Text>
            <Text variant="micro" tone="dim">
              TRUSTED
            </Text>
            <Text variant="micro" tone="bright">
              {trustedCount()}
            </Text>
            <InfoHint label={TRUST_HINT} size={12} />
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

      <Show when={expanded() && hasTools()}>
        <For each={props.server.tools}>
          {(tool) => (
            <ListRow
              label={tool.name}
              leading="code"
              right={
                <Row gap={3} align="center">
                  <ExpandableText
                    text={tool.description}
                    limit={120}
                    variant="micro"
                    tone="dim"
                    class="max-w-xs"
                  />
                  <Tooltip label={TRUST_HINT} side="left">
                    <Row gap={2} align="center">
                      <Text
                        variant="micro"
                        tone={tool.trusted ? "bright" : "dim"}
                      >
                        {tool.trusted ? "TRUSTED" : "ASKS FIRST"}
                      </Text>
                      <Toggle
                        checked={tool.trusted}
                        disabled={!tool.enabled}
                        onChange={(v) =>
                          props.onSetToolPolicy(props.server.id, tool.name, {
                            trusted: v,
                          })
                        }
                      />
                    </Row>
                  </Tooltip>
                  <Tooltip
                    label="Whether this tool is offered to the agent at all."
                    side="left"
                  >
                    <Row gap={2} align="center">
                      <Text variant="micro" tone="dim">
                        ENABLED
                      </Text>
                      <Toggle
                        checked={tool.enabled}
                        onChange={(v) =>
                          props.onSetToolPolicy(props.server.id, tool.name, {
                            enabled: v,
                          })
                        }
                      />
                    </Row>
                  </Tooltip>
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
            <InfoHint label={TRANSPORT_HINT} size={12} />
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
  const servers = useMcpServers();
  const [registerOpen, setRegisterOpen] = createSignal(false);
  const [regName, setRegName] = createSignal("");
  const [regTransport, setRegTransport] = createSignal<McpTransport>("stdio");
  const [regUrl, setRegUrl] = createSignal("");
  const [regCommand, setRegCommand] = createSignal("");
  const [registering, setRegistering] = createSignal(false);
  const [connecting, setConnecting] = createSignal<string | null>(null);
  const [authTarget, setAuthTarget] = createSignal<McpServer | null>(null);

  async function setToolPolicy(
    serverId: string,
    toolName: string,
    patch: { enabled?: boolean; trusted?: boolean },
  ) {
    try {
      await setMcpToolPolicy(serverId, toolName, patch);
      if (patch.trusted !== undefined) {
        toast.success(
          patch.trusted
            ? `"${toolName}" will run without asking.`
            : `"${toolName}" will ask for approval again.`,
        );
      }
    } catch (err) {
      toast.error(mcpErrorMessage(err, `Could not update "${toolName}".`));
    }
  }

  async function retryConnection(server: McpServer) {
    setConnecting(server.id);
    try {
      // A refused connection is a 200 carrying the reason, not a thrown error —
      // so the outcome is read off the server that comes back.
      const updated = await connectMcpServer(server.id);
      if (updated.status === "connected") {
        toast.success(
          `"${updated.name}" connected — ${updated.tools.length} tools discovered.`,
        );
      } else {
        toast.error(
          updated.errorMessage ?? `Could not connect to "${updated.name}".`,
        );
      }
    } catch (err) {
      toast.error(mcpErrorMessage(err, `Could not reach "${server.name}".`));
    } finally {
      setConnecting(null);
    }
  }

  async function saveCredentials(serverId: string, creds: McpAuthCredentials) {
    try {
      const updated = await setMcpCredentials(serverId, creds);
      toast.success(`Auth configured for "${updated.name}".`);
    } catch (err) {
      toast.error(mcpErrorMessage(err, "Could not save the credentials."));
    }
  }

  async function deleteServer(server: McpServer) {
    const ok = await confirm({
      title: `Delete server "${server.name}"?`,
      detail: "The agent will lose access to its tools. This cannot be undone.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteMcpServer(server.id);
      toast.success(`"${server.name}" removed.`);
    } catch (err) {
      toast.error(mcpErrorMessage(err, `Could not remove "${server.name}".`));
    }
  }

  const view = createListView({
    source: () => servers() ?? [],
    search: (s) => s.name,
    sorts: {
      name: { label: "NAME", compare: (a, b) => a.name.localeCompare(b.name) },
      status: {
        label: "STATUS",
        compare: (a, b) => a.status.localeCompare(b.status),
      },
    },
    initialSort: "name",
  });

  /** The command line is typed as one string and split into argv here — a
   *  presentation convenience only; the backend stores command and args apart. */
  function commandParts(): { command: string; args: string[] } {
    const [command = "", ...args] = regCommand().trim().split(/\s+/);
    return { command, args };
  }

  const canRegister = () =>
    regName().trim() !== "" &&
    (regTransport() === "stdio" ? regCommand().trim() : regUrl().trim()) !== "";

  async function registerServer() {
    if (!canRegister()) return;
    const name = regName().trim();
    const stdio = regTransport() === "stdio";
    setRegistering(true);
    try {
      const created = await registerMcpServer({
        name,
        transport: regTransport(),
        ...(stdio ? commandParts() : { url: regUrl().trim() }),
      });
      setRegName("");
      setRegUrl("");
      setRegCommand("");
      setRegTransport("stdio");
      setRegisterOpen(false);
      // Registration dials the server, so the result already says whether it works.
      if (created.status === "connected") {
        toast.success(
          `"${name}" registered — ${created.tools.length} tools discovered.`,
        );
      } else {
        toast.error(
          created.errorMessage ??
            `"${name}" registered but did not connect. Use RETRY once it is running.`,
        );
      }
    } catch (err) {
      toast.error(mcpErrorMessage(err, `Could not register "${name}".`));
    } finally {
      setRegistering(false);
    }
  }

  const connectedCount = () =>
    (servers() ?? []).filter((s) => s.status === "connected").length;

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
        <Show
          when={(servers() ?? []).length}
          fallback={
            <EmptyState
              icon="plug"
              message="NO SERVERS"
              hint="Model Context Protocol (MCP) lets the agent call external tools — file access, search, custom APIs — exposed by a server. Register one to get started."
              action={
                <Button onClick={() => setRegisterOpen(true)} leading="plus">
                  REGISTER SERVER
                </Button>
              }
            />
          }
        >
          <Stack gap={4}>
            <Text variant="micro" tone="dim">
              MCP servers expose tools the agent can call. Every one of them
              asks for your approval before it runs until you trust it — one
              tool at a time, never a whole server.
            </Text>
            <ListToolbar
              query={view.query()}
              onQueryChange={view.setQuery}
              placeholder="Search servers…"
              sortKey={view.sortKey()}
              sortOptions={view.sortOptions}
              onSortChange={view.setSort}
              dir={view.dir()}
              onToggleDir={view.toggleDir}
              count={view.count()}
              total={view.total()}
            />
            <Show
              when={view.items().length}
              fallback={
                <EmptyState
                  icon="search"
                  message="NO MATCHES"
                  hint="No servers match your search."
                />
              }
            >
              <For each={view.items()}>
                {(srv) => (
                  <ServerCard
                    server={srv}
                    busy={connecting() === srv.id}
                    onSetToolPolicy={setToolPolicy}
                    onRetry={retryConnection}
                    onConfigureAuth={(s) => setAuthTarget(s)}
                    onDelete={deleteServer}
                  />
                )}
              </For>
            </Show>
          </Stack>
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
              disabled={!canRegister() || registering()}
            >
              {registering() ? "CONNECTING…" : "REGISTER"}
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
          <Select
            label="TRANSPORT"
            value={regTransport()}
            onChange={(v) => setRegTransport(v as McpTransport)}
            options={[
              { value: "stdio", label: "STDIO (LOCAL SUBPROCESS)" },
              { value: "http", label: "HTTP (STREAMABLE)" },
              { value: "sse", label: "SSE" },
            ]}
          />
          <Show
            when={regTransport() === "stdio"}
            fallback={
              <Input
                label="URL"
                value={regUrl()}
                onInput={(e) => setRegUrl(e.currentTarget.value)}
                placeholder="e.g. http://localhost:8080/mcp"
              />
            }
          >
            <Input
              label="COMMAND"
              value={regCommand()}
              onInput={(e) => setRegCommand(e.currentTarget.value)}
              placeholder="e.g. npx -y @modelcontextprotocol/server-name"
            />
          </Show>
          <Text variant="micro" tone="dim">
            Registering connects to the server and discovers its tools. Each
            tool arrives switched on but untrusted, so it will ask before it
            runs. For auth-required servers, use CONFIGURE AUTH on the server
            card.
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
