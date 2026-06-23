import {
  createEffect,
  createMemo,
  createSignal,
  For,
  Show,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  type SelectOption,
  Stack,
  StatusDot,
  StatusFlag,
  Text,
  ThemeToggle,
  Toggle,
  confirm,
  toast,
} from "~/ui";
import { isApiError } from "~/lib/api";
import {
  createEndpoint,
  deleteEndpoint,
  setEndpointEnabled,
  setRoleBinding,
  testEndpoint,
  updateEndpoint,
  useEndpoints,
  useRoles,
} from "../data";
import { BINDABLE_ROLES } from "../model";
import { EmbeddingRoleControls } from "../components/EmbeddingRoleControls";
import {
  EndpointForm,
  type EndpointFormValues,
} from "../components/EndpointForm";
import { SearchProvidersPanel } from "../components/SearchProvidersPanel";
import {
  EndpointHealthFlag,
  healthStatus,
} from "../components/EndpointHealthFlag";
import {
  endpointDiscovery,
  type EndpointDiscovery,
  modelGroups,
  type ModelEndpoint,
} from "~/lib/stores/models";

export function SettingsScreen(): JSX.Element {
  const endpoints = useEndpoints();
  const roles = useRoles();

  /* ── Endpoint form ──────────────────────────────────────────────────────────
     One form, shared with the guided cookbook tab via <EndpointForm/>; this
     screen drives it in `advanced` mode (all fields). The field values are held
     as a single record so the form stays a pure presentation control. */
  const BLANK_FORM: EndpointFormValues = {
    name: "",
    baseUrl: "",
    model: "",
    apiKey: "",
    contextWindow: "",
    nativeTools: true,
    vision: false,
    thinking: false,
  };
  const [formOpen, setFormOpen] = createSignal(false);
  const [editing, setEditing] = createSignal<ModelEndpoint | null>(null);
  const [form, setForm] = createSignal<EndpointFormValues>(BLANK_FORM);
  const setField = <K extends keyof EndpointFormValues>(
    key: K,
    value: EndpointFormValues[K],
  ) => setForm((f) => ({ ...f, [key]: value }));
  const [saving, setSaving] = createSignal(false);

  const openCreate = () => {
    setEditing(null);
    setForm(BLANK_FORM);
    setFormOpen(true);
  };
  const openEdit = (ep: ModelEndpoint) => {
    setEditing(ep);
    setForm({
      name: ep.name,
      baseUrl: ep.baseUrl,
      model: ep.model ?? "",
      apiKey: "",
      contextWindow: ep.contextWindow != null ? String(ep.contextWindow) : "",
      nativeTools: ep.nativeTools,
      vision: ep.vision,
      thinking: ep.thinking,
    });
    setFormOpen(true);
  };

  const valid = () => form().name.trim() !== "" && form().baseUrl.trim() !== "";

  const save = async () => {
    if (!valid() || saving()) return;
    setSaving(true);
    const f = form();
    const cw = f.contextWindow.trim();
    const m = f.model.trim();
    const apiKey = f.apiKey;
    const fields = {
      name: f.name.trim(),
      baseUrl: f.baseUrl.trim(),
      contextWindow: cw ? Number(cw) : null,
      nativeTools: f.nativeTools,
      vision: f.vision,
      thinking: f.thinking,
    };
    try {
      const target = editing();
      if (target) {
        // Always send model so a cleared field unsets the default; the key is
        // only sent when typed (blank = leave the stored key unchanged).
        await updateEndpoint(target.id, {
          ...fields,
          model: m,
          ...(apiKey ? { apiKey } : {}),
        });
        toast.success("Endpoint updated");
      } else {
        await createEndpoint({
          ...fields,
          model: m || undefined,
          apiKey: apiKey || undefined,
        });
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

  /* ── Health probe + enable/disable ──────────────────────────────────────────
     TEST probes the endpoint now (the backend persists the verdict, which the
     re-read reflects on the row) and surfaces the backend's verbatim detail.
     The toggle PATCHes `enabled`; disabling drops the endpoint from the picker. */
  const [testing, setTesting] = createSignal<string | null>(null);
  const runTest = async (ep: ModelEndpoint) => {
    if (testing()) return;
    setTesting(ep.id);
    try {
      const verdict = await testEndpoint(ep.id);
      if (verdict.status === "ok")
        toast.success(`"${ep.name}" — ${verdict.errorDetail}`);
      else toast.error(`"${ep.name}" — ${verdict.errorDetail}`);
    } catch {
      toast.error(`Unable to test "${ep.name}".`);
    } finally {
      setTesting(null);
    }
  };
  const toggleEnabled = async (ep: ModelEndpoint) => {
    try {
      await setEndpointEnabled(ep.id, !ep.enabled);
      toast.success(ep.enabled ? "Endpoint disabled" : "Endpoint enabled");
    } catch {
      toast.error("Unable to update the endpoint.");
    }
  };

  /* ── Role bindings ──────────────────────────────────────────────────────────
     A role binds to an ordered fallback chain (first = primary). The control
     below captures that order explicitly — membership *and* position — so it no
     longer rides on endpoint creation order. */
  const chainFor = (role: string): string[] =>
    roles()?.[role]?.endpointIds ?? [];
  const modelFor = (role: string): string | null =>
    roles()?.[role]?.model ?? null;
  const endpointById = (id: string): ModelEndpoint | undefined =>
    (endpoints() ?? []).find((e) => e.id === id);
  const endpointName = (id: string): string => endpointById(id)?.name ?? id;
  // A chain member's health for the fallback-chain dots: a disabled endpoint
  // reads as dead (the chain auto-switches past it), else its last probe verdict.
  const chainHealth = (id: string): "nominal" | "alert" | "idle" => {
    const ep = endpointById(id);
    if (!ep || !ep.enabled) return "alert";
    return healthStatus(ep.lastStatus);
  };
  const unboundFor = (role: string): ModelEndpoint[] => {
    const bound = new Set(chainFor(role));
    return (endpoints() ?? []).filter((e) => !bound.has(e.id));
  };

  // The models the embedding role's primary endpoint serves, plus an explicit
  // "endpoint default" choice and the current pick (so it stays selectable even
  // if discovery missed it). The backend validates the chosen model is actually
  // an embeddings model on bind.
  const embeddingModelOptions = createMemo<SelectOption[]>(() => {
    const opts: SelectOption[] = [{ value: "", label: "ENDPOINT DEFAULT" }];
    const primary = chainFor("embedding")[0];
    const models = primary
      ? (
          modelGroups().find((g) => g.endpointId === primary)?.choices ?? []
        ).map((c) => c.model)
      : [];
    for (const m of models) opts.push({ value: m, label: m });
    // Keep the current pick selectable even if discovery didn't list it.
    const current = modelFor("embedding");
    if (current && !models.includes(current))
      opts.push({ value: current, label: current });
    return opts;
  });

  // Re-bind preserves the role's pinned model unless a new one is given; a backend
  // rejection (e.g. a non-embeddings model) surfaces its detail to the operator.
  const applyChain = async (
    role: string,
    next: string[],
    model: string | null = modelFor(role),
  ) => {
    try {
      const reindexStarted = await setRoleBinding(role, next, model);
      if (reindexStarted)
        toast.info("Re-embedding memories and chats for the new model…");
    } catch (e) {
      toast.error(
        isApiError(e) ? e.detail : `Unable to update the ${role} role.`,
      );
    }
  };
  const addToRole = (role: string, id: string) =>
    applyChain(role, [...chainFor(role), id]);
  const removeFromRole = (role: string, id: string) =>
    applyChain(
      role,
      chainFor(role).filter((x) => x !== id),
    );
  const moveInRole = (role: string, index: number, dir: -1 | 1) => {
    const chain = [...chainFor(role)];
    const j = index + dir;
    if (j < 0 || j >= chain.length) return;
    [chain[index], chain[j]] = [chain[j], chain[index]];
    return applyChain(role, chain);
  };

  /* ── Discovery status ─────────────────────────────────────────────────────────
     Each endpoint's models are discovered from its provider; surface whether that
     yielded a live list, only the configured default, or nothing usable. */
  // Index discovery by endpoint once per change — O(1) per row instead of a
  // linear scan in each of the N rows.
  const discoveryById = createMemo(() => {
    const m = new Map<string, EndpointDiscovery>();
    for (const d of endpointDiscovery()) m.set(d.endpointId, d);
    return m;
  });
  const discoveryFor = (id: string): EndpointDiscovery | undefined =>
    discoveryById().get(id);
  const discoveryBadge = (
    d: EndpointDiscovery,
  ): { status: "nominal" | "warn" | "alert"; label: string } => {
    if (d.status === "live")
      return {
        status: "nominal",
        label: `${d.discovered} ${d.discovered === 1 ? "MODEL" : "MODELS"}`,
      };
    if (d.status === "default-only")
      return { status: "warn", label: "DEFAULT ONLY" };
    return { status: "alert", label: "NO MODELS" };
  };

  // Surface a saved endpoint that contributes no selectable model — discovery
  // failed and no default is set — so the operator isn't left guessing. Once per
  // endpoint while this screen is open.
  const toasted = new Set<string>();
  createEffect(() => {
    for (const d of endpointDiscovery()) {
      if (d.status !== "unavailable") {
        // Recovered (or never failed) — re-arm so a later regression re-toasts.
        toasted.delete(d.endpointId);
        continue;
      }
      if (toasted.has(d.endpointId)) continue;
      toasted.add(d.endpointId);
      // `supported` distinguishes a working-but-empty models API from one that
      // couldn't be reached, so the operator knows where to look.
      const reason = d.supported
        ? "the provider listed no models"
        : "its models API was unavailable";
      toast.error(
        `No models for "${d.endpointName}" — ${reason}. Set a default model or check the provider.`,
      );
    }
  });

  return (
    <Stack gap={6}>
      <PageHeader
        title="SETTINGS"
        subtitle="Appearance, model, and web-search configuration."
        assetId="ODY-CFG-03.0"
      />

      <Panel label="APPEARANCE">
        <Row align="center" justify="between">
          <Stack gap={1}>
            <Text variant="label" tone="default">
              THEME
            </Text>
            <Text variant="micro" tone="dim">
              Phosphor (dark), Paper (light), or follow system. Stored locally
              on this device.
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
        <Show when={endpoints.latest} fallback={<LoadingText />}>
          <Show
            when={(endpoints.latest ?? []).length}
            fallback={
              <EmptyState
                icon="cpu"
                message="NO ENDPOINTS"
                hint="Add an OpenAI-compatible endpoint to pick its models from the top bar."
              />
            }
          >
            <Stack gap={0}>
              <For each={endpoints.latest ?? []}>
                {(ep) => (
                  <Row
                    align="center"
                    justify="between"
                    gap={3}
                    class="border-b border-line py-2 last:border-0"
                  >
                    <Stack
                      gap={1}
                      class={`min-w-0 ${ep.enabled ? "" : "opacity-40"}`}
                    >
                      <Row gap={2} align="center">
                        <Text variant="label" tone="bright">
                          {ep.name}
                        </Text>
                        <EndpointHealthFlag status={ep.lastStatus} />
                        <Show when={!ep.enabled}>
                          <StatusFlag status="warn">DISABLED</StatusFlag>
                        </Show>
                        <Show when={ep.hasApiKey}>
                          <StatusFlag status="nominal">KEY</StatusFlag>
                        </Show>
                        <Show when={ep.vision}>
                          <StatusFlag status="info">VIS</StatusFlag>
                        </Show>
                        <Show when={ep.thinking}>
                          <StatusFlag status="info">THINK</StatusFlag>
                        </Show>
                        <Show when={discoveryFor(ep.id)}>
                          {(d) => (
                            <StatusFlag status={discoveryBadge(d()).status}>
                              {discoveryBadge(d()).label}
                            </StatusFlag>
                          )}
                        </Show>
                      </Row>
                      <Text variant="micro" tone="dim" class="truncate">
                        {ep.model ? `${ep.model} · ${ep.baseUrl}` : ep.baseUrl}
                      </Text>
                      {/* Backend-authored failure sentence — rendered verbatim. */}
                      <Show
                        when={ep.lastStatus === "error" && ep.lastErrorDetail}
                      >
                        <Text variant="micro" tone="alert">
                          {ep.lastErrorDetail}
                        </Text>
                      </Show>
                    </Stack>
                    <span class="flex shrink-0 items-center gap-2">
                      <Toggle
                        checked={ep.enabled}
                        onChange={() => void toggleEnabled(ep)}
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        leading="refresh"
                        disabled={testing() === ep.id}
                        onClick={() => void runTest(ep)}
                      >
                        {testing() === ep.id ? "TESTING…" : "TEST"}
                      </Button>
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
        </Show>
      </Panel>

      <Panel label="ROLE BINDINGS">
        <Stack gap={4}>
          <Text variant="micro" tone="dim">
            Bind endpoints to each role as an ordered fallback chain (first =
            primary). `utility` runs background verification; `embedding` powers
            memory recall. The chat (`main`) model is chosen from the model
            picker in the top bar. Auto-switches past dead/disabled endpoints.
          </Text>
          <Show
            when={(endpoints() ?? []).length}
            fallback={
              <Text variant="micro" tone="dim">
                Add an endpoint to bind roles.
              </Text>
            }
          >
            <For each={BINDABLE_ROLES}>
              {(role) => (
                <Stack gap={2}>
                  <Text variant="label" tone="bright">
                    {role.toUpperCase()}
                  </Text>
                  <Show
                    when={chainFor(role).length}
                    fallback={
                      <Text variant="micro" tone="dim">
                        No endpoints bound — add one below.
                      </Text>
                    }
                  >
                    <Stack gap={0}>
                      <For each={chainFor(role)}>
                        {(id, i) => (
                          <Row
                            align="center"
                            justify="between"
                            gap={2}
                            class="border-b border-line py-1.5 last:border-0"
                          >
                            <Row gap={2} align="center" class="min-w-0">
                              <Text variant="micro" tone="dim">
                                {i() + 1}
                              </Text>
                              <StatusDot status={chainHealth(id)} />
                              <Text
                                variant="label"
                                tone="default"
                                class="truncate"
                              >
                                {endpointName(id)}
                              </Text>
                              <Show when={i() === 0}>
                                <StatusFlag status="nominal">
                                  PRIMARY
                                </StatusFlag>
                              </Show>
                            </Row>
                            <span class="flex shrink-0 items-center gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="chevron-up"
                                aria-label="Move earlier in the chain"
                                disabled={i() === 0}
                                onClick={() => void moveInRole(role, i(), -1)}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="chevron-down"
                                aria-label="Move later in the chain"
                                disabled={i() === chainFor(role).length - 1}
                                onClick={() => void moveInRole(role, i(), 1)}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="close"
                                aria-label="Remove from the chain"
                                onClick={() => void removeFromRole(role, id)}
                              />
                            </span>
                          </Row>
                        )}
                      </For>
                    </Stack>
                  </Show>
                  <Show when={unboundFor(role).length}>
                    <div class="flex flex-wrap gap-2">
                      <For each={unboundFor(role)}>
                        {(ep) => (
                          <Button
                            variant="ghost"
                            size="sm"
                            leading="plus"
                            onClick={() => void addToRole(role, ep.id)}
                          >
                            {ep.name}
                          </Button>
                        )}
                      </For>
                    </div>
                  </Show>
                  <Show when={role === "embedding"}>
                    <EmbeddingRoleControls
                      bound={chainFor("embedding").length > 0}
                      model={modelFor("embedding")}
                      modelOptions={embeddingModelOptions()}
                      onPickModel={(m) =>
                        void applyChain("embedding", chainFor("embedding"), m)
                      }
                    />
                  </Show>
                </Stack>
              )}
            </For>
          </Show>
        </Stack>
      </Panel>

      <SearchProvidersPanel />

      {/* Endpoint form */}
      <Modal
        open={formOpen()}
        onClose={() => setFormOpen(false)}
        title={editing() ? "EDIT ENDPOINT" : "ADD ENDPOINT"}
        class="max-w-lg"
      >
        <Stack gap={3}>
          <EndpointForm
            variant="advanced"
            editing={!!editing()}
            values={form()}
            onChange={setField}
          />
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
