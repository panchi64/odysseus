import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  confirm,
  EmptyState,
  ExpandableText,
  Field,
  InfoHint,
  Input,
  ListRow,
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
import { timestamp } from "~/lib/format";
import {
  configureIntegration,
  deleteIntegration,
  integrationErrorMessage,
  setIntegrationActionPolicy,
  testIntegration,
  updateIntegration,
  useIntegrationPresets,
  useIntegrations,
} from "../data";
import type { Integration, IntegrationStatus } from "../model";

const TRUST_HINT =
  "A connector action reaches a third-party service on your behalf, so every call pauses for your approval by default. Trust one you've vetted to let it run without asking — one action at a time, and revocable at any moment.";

const intStatusFlag: Record<IntegrationStatus, Status> = {
  ok: "nominal",
  untested: "idle",
  error: "alert",
};

// ---------------------------------------------------------------------------
// Connector card
// ---------------------------------------------------------------------------

function ConnectorCard(props: {
  integration: Integration;
  busy: boolean;
  onSetActionPolicy: (
    integrationId: string,
    actionName: string,
    patch: { enabled?: boolean; trusted?: boolean },
  ) => void;
  onTest: (integration: Integration) => void;
  onConfigure: (integration: Integration) => void;
  onDelete: (integration: Integration) => void;
}): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const actions = () => props.integration.actions;
  const trustedCount = () => actions().filter((a) => a.trusted).length;

  return (
    <Panel
      label={props.integration.name}
      state={props.integration.status === "error" ? "alert" : "default"}
      meta={
        <Row gap={2} align="center">
          <Text variant="micro" tone="dim">
            {props.integration.type}
          </Text>
          <StatusFlag
            status={props.integration.configured ? "nominal" : "idle"}
          >
            {props.integration.configured ? "CONFIGURED" : "NOT SET"}
          </StatusFlag>
          <Show
            when={props.integration.status === "error"}
            fallback={
              <StatusFlag status={intStatusFlag[props.integration.status]}>
                {props.integration.status.toUpperCase()}
              </StatusFlag>
            }
          >
            <Tooltip
              label={props.integration.errorMessage ?? "Unknown error"}
              side="left"
            >
              <StatusFlag status="alert">ERROR</StatusFlag>
            </Tooltip>
          </Show>

          <Button
            size="sm"
            variant="ghost"
            leading="activity"
            disabled={props.busy}
            onClick={() => props.onTest(props.integration)}
          >
            {props.busy ? "TESTING…" : "TEST"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            leading="settings"
            onClick={() => props.onConfigure(props.integration)}
          >
            CONFIGURE
          </Button>
          <Show when={actions().length}>
            <Button
              size="sm"
              variant="ghost"
              trailing={expanded() ? "chevron-down" : "chevron-right"}
              onClick={() => setExpanded((v) => !v)}
            >
              {actions().length} ACTIONS
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
                label: "REMOVE CONNECTOR",
                icon: "trash",
                danger: true,
                onSelect: () => props.onDelete(props.integration),
              },
            ]}
          />
        </Row>
      }
      flush={expanded() && actions().length > 0}
    >
      <Show when={!expanded()}>
        <Stack gap={2}>
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              BASE URL
            </Text>
            <Text variant="micro" tone="bright">
              {props.integration.baseUrl}
            </Text>
          </Row>
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              ACTIONS TRUSTED
            </Text>
            <Text variant="micro" tone="nominal">
              {trustedCount()} / {actions().length}
            </Text>
            <InfoHint label={TRUST_HINT} size={12} />
          </Row>
          <Show when={props.integration.lastTestedAt}>
            <Row gap={2} align="center">
              <Text variant="micro" tone="dim">
                LAST TESTED
              </Text>
              <Text variant="micro" tone="bright">
                {timestamp(props.integration.lastTestedAt!)}
              </Text>
            </Row>
          </Show>
          <Show when={props.integration.errorMessage}>
            <Row gap={2} align="center">
              <Text variant="micro" tone="dim">
                LAST ERROR
              </Text>
              <Text variant="micro" tone="alert">
                {props.integration.errorMessage}
              </Text>
            </Row>
          </Show>
        </Stack>
      </Show>

      <Show when={expanded() && actions().length}>
        <For each={actions()}>
          {(action) => (
            <ListRow
              label={action.name}
              leading="link"
              right={
                <Row gap={3} align="center">
                  <Text variant="micro" tone="dim">
                    {action.method}
                  </Text>
                  <ExpandableText
                    text={action.description}
                    limit={100}
                    variant="micro"
                    tone="dim"
                    class="max-w-xs"
                  />
                  <Tooltip label={TRUST_HINT} side="left">
                    <Row gap={2} align="center">
                      <Text
                        variant="micro"
                        tone={action.trusted ? "bright" : "dim"}
                      >
                        {action.trusted ? "TRUSTED" : "ASKS FIRST"}
                      </Text>
                      <Toggle
                        checked={action.trusted}
                        disabled={!action.enabled}
                        onChange={(v) =>
                          props.onSetActionPolicy(
                            props.integration.id,
                            action.name,
                            { trusted: v },
                          )
                        }
                      />
                    </Row>
                  </Tooltip>
                  <Tooltip
                    label="Whether this action is offered to the agent at all."
                    side="left"
                  >
                    <Row gap={2} align="center">
                      <Text variant="micro" tone="dim">
                        ENABLED
                      </Text>
                      <Toggle
                        checked={action.enabled}
                        onChange={(v) =>
                          props.onSetActionPolicy(
                            props.integration.id,
                            action.name,
                            { enabled: v },
                          )
                        }
                      />
                    </Row>
                  </Tooltip>
                </Row>
              }
            />
          )}
        </For>
      </Show>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// IntegrationsScreen
// ---------------------------------------------------------------------------

export function IntegrationsScreen(): JSX.Element {
  const integrations = useIntegrations();
  const presets = useIntegrationPresets();

  const [addOpen, setAddOpen] = createSignal(false);
  const [addPreset, setAddPreset] = createSignal("");
  const [addName, setAddName] = createSignal("");
  const [addUrl, setAddUrl] = createSignal("");
  const [addKey, setAddKey] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  const [editing, setEditing] = createSignal<Integration | null>(null);
  const [editUrl, setEditUrl] = createSignal("");
  const [editKey, setEditKey] = createSignal("");
  const [testingId, setTestingId] = createSignal<string | null>(null);

  const chosenPreset = () =>
    (presets() ?? []).find((p) => p.id === addPreset());

  function openAdd() {
    const first = (presets() ?? [])[0];
    setAddPreset(first?.id ?? "");
    setAddName("");
    setAddUrl("");
    setAddKey("");
    setAddOpen(true);
  }

  async function saveNew() {
    const preset = chosenPreset();
    if (!preset) return;
    setSaving(true);
    try {
      const created = await configureIntegration({
        preset: preset.id,
        name: addName().trim() || undefined,
        baseUrl: addUrl().trim() || undefined,
        credentials: addKey().trim() ? { token: addKey().trim() } : undefined,
      });
      setAddOpen(false);
      toast.success(`"${created.name}" configured. Run TEST to prove it.`);
    } catch (err) {
      toast.error(
        integrationErrorMessage(err, "Could not configure the connector."),
      );
    } finally {
      setSaving(false);
    }
  }

  function openConfig(integration: Integration) {
    setEditing(integration);
    setEditUrl(integration.baseUrl);
    setEditKey("");
  }

  async function saveConfig() {
    const target = editing();
    if (!target) return;
    setSaving(true);
    try {
      await updateIntegration(target.id, {
        baseUrl: editUrl().trim() || undefined,
        // Omitted rather than blanked: a credential goes in and never comes back,
        // so an empty box means "leave what is stored", not "clear it".
        credentials: editKey().trim() ? { token: editKey().trim() } : undefined,
      });
      setEditing(null);
      toast.success(`"${target.name}" saved.`);
    } catch (err) {
      toast.error(integrationErrorMessage(err, "Could not save the changes."));
    } finally {
      setSaving(false);
    }
  }

  async function runTest(integration: Integration) {
    setTestingId(integration.id);
    try {
      // A rejected credential answers 200 with the reason — that outcome is what
      // was asked for, so it is read off the connector rather than thrown.
      const tested = await testIntegration(integration.id);
      if (tested.status === "ok") {
        toast.success(`"${tested.name}" answered — the credential works.`);
      } else {
        toast.error(tested.errorMessage ?? `"${tested.name}" did not answer.`);
      }
    } catch (err) {
      toast.error(
        integrationErrorMessage(err, `Could not test "${integration.name}".`),
      );
    } finally {
      setTestingId(null);
    }
  }

  async function setActionPolicy(
    integrationId: string,
    actionName: string,
    patch: { enabled?: boolean; trusted?: boolean },
  ) {
    try {
      await setIntegrationActionPolicy(integrationId, actionName, patch);
      if (patch.trusted !== undefined) {
        toast.success(
          patch.trusted
            ? `"${actionName}" will run without asking.`
            : `"${actionName}" will ask for approval again.`,
        );
      }
    } catch (err) {
      toast.error(
        integrationErrorMessage(err, `Could not update "${actionName}".`),
      );
    }
  }

  async function removeIntegration(integration: Integration) {
    const ok = await confirm({
      title: `Remove "${integration.name}"?`,
      detail:
        "Its stored credential is deleted and the agent loses its actions. This cannot be undone.",
      confirmLabel: "REMOVE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteIntegration(integration.id);
      toast.success(`"${integration.name}" removed.`);
    } catch (err) {
      toast.error(
        integrationErrorMessage(err, `Could not remove "${integration.name}".`),
      );
    }
  }

  const configuredCount = () =>
    (integrations() ?? []).filter((i) => i.configured).length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="INTEGRATIONS"
        subtitle="HTTP service connectors. Credentials are encrypted at rest."
        assetId="SYS-INT-05.1"
        actions={
          <Row gap={2} align="center">
            <StatusFlag status="nominal">{`${configuredCount()} CONFIGURED`}</StatusFlag>
            <Button variant="default" leading="plus" onClick={openAdd}>
              ADD CONNECTOR
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING INTEGRATIONS" />}>
        <Show
          when={(integrations() ?? []).length}
          fallback={
            <EmptyState
              icon="plug"
              message="NO INTEGRATIONS"
              hint="Connectors let the agent reach a third-party service — GitHub, Jira, Slack — with a credential you store here. Add one to get started."
              action={
                <Button onClick={openAdd} leading="plus">
                  ADD CONNECTOR
                </Button>
              }
            />
          }
        >
          <Stack gap={4}>
            <Text variant="micro" tone="dim">
              Every connector action asks for your approval before it runs until
              you trust it — one action at a time, never a whole connector.
            </Text>
            <For each={integrations()}>
              {(int) => (
                <ConnectorCard
                  integration={int}
                  busy={testingId() === int.id}
                  onSetActionPolicy={setActionPolicy}
                  onTest={runTest}
                  onConfigure={openConfig}
                  onDelete={removeIntegration}
                />
              )}
            </For>
          </Stack>
        </Show>
      </Suspense>

      {/* Add from a preset */}
      <Modal
        open={addOpen()}
        onClose={() => setAddOpen(false)}
        title="ADD CONNECTOR"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={saveNew}
              disabled={!chosenPreset() || saving()}
            >
              {saving() ? "SAVING…" : "ADD"}
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Select
            label="SERVICE"
            value={addPreset()}
            onChange={setAddPreset}
            options={(presets() ?? []).map((p) => ({
              value: p.id,
              label: p.name.toUpperCase(),
            }))}
          />
          <Show when={chosenPreset()}>
            {(preset) => (
              <Stack gap={4}>
                <Text variant="micro" tone="dim">
                  {preset().description}
                </Text>
                <Input
                  label="NAME (OPTIONAL)"
                  value={addName()}
                  onInput={(e) => setAddName(e.currentTarget.value)}
                  placeholder={preset().name}
                />
                <Input
                  label="BASE URL (OPTIONAL — FOR A SELF-HOSTED INSTANCE)"
                  value={addUrl()}
                  onInput={(e) => setAddUrl(e.currentTarget.value)}
                  placeholder={preset().baseUrl}
                />
                <Input
                  label={
                    preset().credentialRequired
                      ? "API KEY / TOKEN (REQUIRED)"
                      : "API KEY / TOKEN (OPTIONAL)"
                  }
                  type="password"
                  value={addKey()}
                  onInput={(e) => setAddKey(e.currentTarget.value)}
                  placeholder={
                    preset().credentialRequired
                      ? "Required for this connector"
                      : "Optional for this connector"
                  }
                />
                <Text variant="micro" tone="dim">
                  {preset().actions.length} actions become available, each
                  switched on but untrusted — they will ask before they run.
                </Text>
              </Stack>
            )}
          </Show>
        </Stack>
      </Modal>

      {/* Configure an existing connector */}
      <Modal
        open={editing() !== null}
        onClose={() => setEditing(null)}
        title={`CONFIGURE — ${editing()?.name ?? ""}`}
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              CANCEL
            </Button>
            <Button variant="primary" onClick={saveConfig} disabled={saving()}>
              {saving() ? "SAVING…" : "SAVE"}
            </Button>
          </Row>
        }
      >
        <Show when={editing()}>
          {(int) => (
            <Stack gap={4}>
              <Show when={int().description}>
                <Text variant="micro" tone="dim">
                  {int().description}
                </Text>
              </Show>

              <Row gap={4} align="center">
                <Field label="TYPE" value={int().type} />
                <Field label="ID" value={int().id} />
              </Row>

              <Input
                label="BASE URL"
                value={editUrl()}
                onInput={(e) => setEditUrl(e.currentTarget.value)}
                placeholder="https://api.example.com"
              />
              <Input
                label={
                  int().credentialRequired
                    ? "API KEY / CREDENTIAL (REQUIRED)"
                    : "API KEY / CREDENTIAL (OPTIONAL)"
                }
                type="password"
                value={editKey()}
                onInput={(e) => setEditKey(e.currentTarget.value)}
                placeholder={
                  int().configured
                    ? "Leave blank to keep the stored credential"
                    : "Paste your key here"
                }
              />

              <Show when={int().lastTestedAt}>
                <Field
                  label="LAST TESTED"
                  value={timestamp(int().lastTestedAt!)}
                />
              </Show>

              <Text variant="micro" tone="dim">
                Credentials are encrypted at rest and never read back. Save,
                then run TEST on the card to prove the credential before relying
                on it.
              </Text>
            </Stack>
          )}
        </Show>
      </Modal>
    </Stack>
  );
}
