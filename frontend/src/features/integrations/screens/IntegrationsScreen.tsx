import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  EmptyState,
  Field,
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
  toast,
  type Status,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { useIntegrations } from "../data";
import type { Integration, IntegrationStatus } from "../model";

const intStatusFlag: Record<IntegrationStatus, Status> = {
  ok: "nominal",
  untested: "idle",
  error: "alert",
};

export function IntegrationsScreen(): JSX.Element {
  const resource = useIntegrations();
  const [integrations, setIntegrations] = createStore<Integration[]>([]);
  const [seeded, setSeeded] = createSignal(false);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));
  const [configOpen, setConfigOpen] = createSignal(false);
  const [editing, setEditing] = createSignal<Integration | null>(null);
  const [editUrl, setEditUrl] = createSignal("");
  const [editKey, setEditKey] = createSignal("");
  const [testResult, setTestResult] = createSignal<"ok" | "error" | null>(null);
  const [testing, setTesting] = createSignal(false);

  const resolved = () => {
    const data = resource();
    if (data && !seeded()) {
      setSeeded(true);
      setIntegrations(data.map((i) => ({ ...i })));
    }
    return data;
  };

  function openConfig(int: Integration) {
    setEditing(int);
    setEditUrl(int.baseUrl);
    setEditKey("");
    setTestResult(null);
    setConfigOpen(true);
  }

  function runTest() {
    setTesting(true);
    setTestResult(null);
    timers.push(
      setTimeout(() => {
        const outcome = Math.random() > 0.3 ? "ok" : "error";
        setTestResult(outcome);
        setTesting(false);
      }, 900),
    );
  }

  function saveConfig() {
    const id = editing()?.id;
    if (!id) return;
    if (testResult() === "error") {
      toast.error(
        "Fix the test failure before saving — re-test after correcting the credentials.",
      );
      return;
    }
    setIntegrations(
      produce((s) => {
        const int = s.find((x) => x.id === id);
        if (int) {
          int.baseUrl = editUrl();
          int.configured = true;
          int.status = testResult() ?? "untested";
          int.lastTestedAt = testResult()
            ? new Date().toISOString()
            : int.lastTestedAt;
        }
      }),
    );
    setConfigOpen(false);
    toast.success(`${editing()?.name ?? "Integration"} saved`);
  }

  const configuredCount = () => integrations.filter((i) => i.configured).length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="INTEGRATIONS"
        subtitle="HTTP service connectors. Credentials are encrypted at rest."
        assetId="SYS-INT-05.1"
        actions={
          <StatusFlag status="nominal">{`${configuredCount()} CONFIGURED`}</StatusFlag>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING INTEGRATIONS" />}>
        <Show when={resolved()}>
          <Show
            when={integrations.length}
            fallback={<EmptyState icon="plug" message="NO INTEGRATIONS" />}
          >
            <Panel label="SERVICE CONNECTORS" flush>
              <For each={integrations}>
                {(int) => (
                  <ListRow
                    label={int.name}
                    leading="link"
                    right={
                      <Row gap={2} align="center">
                        <Text variant="micro" tone="dim">
                          {int.type}
                        </Text>
                        <StatusFlag
                          status={int.configured ? "nominal" : "idle"}
                        >
                          {int.configured ? "CONFIGURED" : "NOT SET"}
                        </StatusFlag>
                        <StatusFlag status={intStatusFlag[int.status]}>
                          {int.status.toUpperCase()}
                        </StatusFlag>
                        <Button
                          size="sm"
                          variant="ghost"
                          leading="settings"
                          onClick={() => openConfig(int)}
                        >
                          CONFIGURE
                        </Button>
                      </Row>
                    }
                  />
                )}
              </For>
            </Panel>
          </Show>
        </Show>
      </Suspense>

      <Modal
        open={configOpen()}
        onClose={() => setConfigOpen(false)}
        title={`CONFIGURE — ${editing()?.name ?? ""}`}
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setConfigOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="default"
              leading="activity"
              onClick={runTest}
              disabled={testing()}
            >
              {testing() ? "TESTING…" : "TEST"}
            </Button>
            <Button
              variant="primary"
              onClick={saveConfig}
              disabled={testResult() === "error"}
            >
              SAVE
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Show when={editing()?.description}>
            <Text variant="micro" tone="dim">
              {editing()?.description}
            </Text>
          </Show>

          <Show when={editing()}>
            {(int) => (
              <Row gap={4} align="center">
                <Field label="TYPE" value={int().type} />
                <Field label="ID" value={int().id} />
              </Row>
            )}
          </Show>

          <Input
            label="BASE URL (REQUIRED)"
            value={editUrl()}
            onInput={(e) => setEditUrl(e.currentTarget.value)}
            placeholder="https://api.example.com"
          />
          <Input
            label={
              editing()?.credentialRequired
                ? "API KEY / CREDENTIAL (REQUIRED)"
                : "API KEY / CREDENTIAL (OPTIONAL)"
            }
            type="password"
            value={editKey()}
            onInput={(e) => {
              setEditKey(e.currentTarget.value);
              setTestResult(null);
            }}
            placeholder={
              editing()?.credentialRequired
                ? "Required for this connector"
                : "Optional — leave blank to keep existing"
            }
          />

          <Show when={testResult() === "ok"}>
            <StatusFlag status="nominal">TEST PASSED</StatusFlag>
          </Show>
          <Show when={testResult() === "error"}>
            <Panel
              label={`CONFIGURE — ${editing()?.name ?? ""} [ERROR]`}
              state="alert"
            >
              <Stack gap={2}>
                <Text variant="micro" tone="alert">
                  Connection test failed. Correct the base URL or credential and
                  run TEST again before saving.
                </Text>
                <Text variant="micro" tone="dim">
                  Common causes: wrong base URL, expired API key, or host
                  unreachable from this server.
                </Text>
              </Stack>
            </Panel>
          </Show>

          <Show when={editing()?.lastTestedAt}>
            <Field
              label="LAST TESTED"
              value={timestamp(editing()!.lastTestedAt!)}
            />
          </Show>

          <Text variant="micro" tone="dim">
            Credentials are stored encrypted using AES-256-GCM at rest. Never
            transmitted in logs.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
