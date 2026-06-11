import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  Checkbox,
  EmptyState,
  Field,
  Input,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  ThemeToggle,
  Toggle,
  confirm,
  toast,
} from "~/ui";
import {
  createEndpoint,
  deleteEndpoint,
  setRoleBinding,
  updateEndpoint,
  useEndpoints,
  useRoles,
} from "../data";
import { MODEL_ROLES, type ModelEndpoint } from "../model";

export function SettingsScreen(): JSX.Element {
  const endpoints = useEndpoints();
  const roles = useRoles();

  /* ── Endpoint form ──────────────────────────────────────────────────────── */
  const [formOpen, setFormOpen] = createSignal(false);
  const [editing, setEditing] = createSignal<ModelEndpoint | null>(null);
  const [name, setName] = createSignal("");
  const [baseUrl, setBaseUrl] = createSignal("");
  const [model, setModel] = createSignal("");
  const [apiKey, setApiKey] = createSignal("");
  const [contextWindow, setContextWindow] = createSignal("");
  const [nativeTools, setNativeTools] = createSignal(true);
  const [vision, setVision] = createSignal(false);
  const [thinking, setThinking] = createSignal(false);
  const [saving, setSaving] = createSignal(false);

  const openCreate = () => {
    setEditing(null);
    setName("");
    setBaseUrl("");
    setModel("");
    setApiKey("");
    setContextWindow("");
    setNativeTools(true);
    setVision(false);
    setThinking(false);
    setFormOpen(true);
  };
  const openEdit = (ep: ModelEndpoint) => {
    setEditing(ep);
    setName(ep.name);
    setBaseUrl(ep.baseUrl);
    setModel(ep.model);
    setApiKey("");
    setContextWindow(ep.contextWindow != null ? String(ep.contextWindow) : "");
    setNativeTools(ep.nativeTools);
    setVision(ep.vision);
    setThinking(ep.thinking);
    setFormOpen(true);
  };

  const valid = () =>
    name().trim() !== "" && baseUrl().trim() !== "" && model().trim() !== "";

  const save = async () => {
    if (!valid() || saving()) return;
    setSaving(true);
    const cw = contextWindow().trim();
    const fields = {
      name: name().trim(),
      baseUrl: baseUrl().trim(),
      model: model().trim(),
      contextWindow: cw ? Number(cw) : null,
      nativeTools: nativeTools(),
      vision: vision(),
      thinking: thinking(),
    };
    try {
      const target = editing();
      if (target) {
        // Only send the key if the operator typed one (blank = leave unchanged).
        await updateEndpoint(target.id, {
          ...fields,
          ...(apiKey() ? { apiKey: apiKey() } : {}),
        });
        toast.success("Endpoint updated");
      } else {
        await createEndpoint({ ...fields, apiKey: apiKey() || undefined });
        toast.success("Endpoint added");
      }
      setFormOpen(false);
    } catch {
      toast.error("Unable to save the endpoint.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (ep: ModelEndpoint) => {
    if (
      !(await confirm({
        title: `Delete endpoint "${ep.name}"?`,
        detail: "Any role bound to it will fall back to its remaining chain.",
        confirmLabel: "DELETE",
        tone: "alert",
      }))
    )
      return;
    try {
      await deleteEndpoint(ep.id);
      toast.success("Endpoint deleted");
    } catch {
      toast.error("Unable to delete the endpoint.");
    }
  };

  /* ── Role bindings ──────────────────────────────────────────────────────── */
  const isBound = (role: string, endpointId: string) =>
    (roles()?.[role] ?? []).includes(endpointId);

  const toggleBinding = async (role: string, endpointId: string) => {
    const current = roles()?.[role] ?? [];
    const all = endpoints() ?? [];
    const wanted = new Set(
      current.includes(endpointId)
        ? current.filter((id) => id !== endpointId)
        : [...current, endpointId],
    );
    // Keep the chain in endpoint-list order (first = primary).
    const next = all.filter((e) => wanted.has(e.id)).map((e) => e.id);
    try {
      await setRoleBinding(role, next);
    } catch {
      toast.error(`Unable to update the ${role} role.`);
    }
  };

  return (
    <Stack gap={6}>
      <PageHeader
        title="SETTINGS"
        subtitle="Appearance and model configuration."
        assetId="ODY-CFG-03.0"
      />

      <Panel label="APPEARANCE">
        <Row align="center" justify="between">
          <Stack gap={1}>
            <Text variant="label" tone="default">
              THEME
            </Text>
            <Text variant="micro" tone="dim">
              Phosphor (dark) or Paper (light). Stored locally on this device.
            </Text>
          </Stack>
          <ThemeToggle />
        </Row>
      </Panel>

      <Panel
        label="MODEL ENDPOINTS"
        meta={
          <Button
            variant="primary"
            size="sm"
            leading="plus"
            onClick={openCreate}
          >
            ADD ENDPOINT
          </Button>
        }
      >
        <Suspense fallback={<LoadingText />}>
          <Show
            when={(endpoints() ?? []).length}
            fallback={
              <EmptyState
                icon="cpu"
                message="NO ENDPOINTS"
                hint="Add an OpenAI-compatible endpoint, then bind it to a role below."
              />
            }
          >
            <Stack gap={0}>
              <For each={endpoints() ?? []}>
                {(ep) => (
                  <Row
                    align="center"
                    justify="between"
                    gap={3}
                    class="border-b border-line py-2 last:border-0"
                  >
                    <Stack gap={1} class="min-w-0">
                      <Row gap={2} align="center">
                        <Text variant="label" tone="bright">
                          {ep.name}
                        </Text>
                        <Show when={ep.hasApiKey}>
                          <StatusFlag status="nominal">KEY</StatusFlag>
                        </Show>
                        <Show when={ep.vision}>
                          <StatusFlag status="info">VIS</StatusFlag>
                        </Show>
                        <Show when={ep.thinking}>
                          <StatusFlag status="info">THINK</StatusFlag>
                        </Show>
                      </Row>
                      <Text variant="micro" tone="dim" class="truncate">
                        {ep.model} · {ep.baseUrl}
                      </Text>
                    </Stack>
                    <span class="flex shrink-0 items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        leading="edit"
                        onClick={() => openEdit(ep)}
                      >
                        EDIT
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        leading="trash"
                        onClick={() => remove(ep)}
                      >
                        DELETE
                      </Button>
                    </span>
                  </Row>
                )}
              </For>
            </Stack>
          </Show>
        </Suspense>
      </Panel>

      <Panel label="ROLE BINDINGS">
        <Stack gap={4}>
          <Text variant="micro" tone="dim">
            Bind endpoints to each role as an ordered fallback chain (first =
            primary). `main` answers chat; `utility` runs verification;
            `embedding` powers memory recall.
          </Text>
          <Show
            when={(endpoints() ?? []).length}
            fallback={
              <Text variant="micro" tone="dim">
                Add an endpoint to bind roles.
              </Text>
            }
          >
            <For each={MODEL_ROLES}>
              {(role) => (
                <Stack gap={2}>
                  <Text variant="label" tone="bright">
                    {role.toUpperCase()}
                  </Text>
                  <div class="flex flex-wrap gap-3">
                    <For each={endpoints() ?? []}>
                      {(ep) => (
                        <Checkbox
                          label={ep.name}
                          checked={isBound(role, ep.id)}
                          onChange={() => void toggleBinding(role, ep.id)}
                        />
                      )}
                    </For>
                  </div>
                </Stack>
              )}
            </For>
          </Show>
        </Stack>
      </Panel>

      {/* Endpoint form */}
      <Modal
        open={formOpen()}
        onClose={() => setFormOpen(false)}
        title={editing() ? "EDIT ENDPOINT" : "ADD ENDPOINT"}
        class="max-w-lg"
      >
        <Stack gap={3}>
          <Input
            label="NAME"
            value={name()}
            onInput={(e) => setName(e.currentTarget.value)}
            placeholder="e.g. local-qwen"
          />
          <Input
            label="BASE URL"
            value={baseUrl()}
            onInput={(e) => setBaseUrl(e.currentTarget.value)}
            placeholder="http://localhost:11434/v1"
          />
          <Input
            label="MODEL"
            value={model()}
            onInput={(e) => setModel(e.currentTarget.value)}
            placeholder="qwen2.5-coder:32b"
          />
          <Input
            label={
              editing() ? "API KEY (blank = unchanged)" : "API KEY (optional)"
            }
            type="password"
            value={apiKey()}
            onInput={(e) => setApiKey(e.currentTarget.value)}
            placeholder="••••••••"
          />
          <Input
            label="CONTEXT WINDOW (optional)"
            value={contextWindow()}
            onInput={(e) => setContextWindow(e.currentTarget.value)}
            placeholder="32768"
          />
          <Row gap={4} align="center" justify="between">
            <Field label="NATIVE TOOLS" orientation="row" value="" />
            <Toggle checked={nativeTools()} onChange={setNativeTools} />
          </Row>
          <Row gap={4} align="center" justify="between">
            <Field label="VISION" orientation="row" value="" />
            <Toggle checked={vision()} onChange={setVision} />
          </Row>
          <Row gap={4} align="center" justify="between">
            <Field label="THINKING" orientation="row" value="" />
            <Toggle checked={thinking()} onChange={setThinking} />
          </Row>
          <div class="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setFormOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              disabled={!valid() || saving()}
              onClick={save}
            >
              {saving() ? "SAVING…" : "SAVE"}
            </Button>
          </div>
        </Stack>
      </Modal>
    </Stack>
  );
}
