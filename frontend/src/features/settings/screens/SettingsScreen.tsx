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
import { BINDABLE_ROLES } from "../model";
import { SearchProvidersPanel } from "../components/SearchProvidersPanel";
import {
  endpointDiscovery,
  type EndpointDiscovery,
  type ModelEndpoint,
} from "~/lib/stores/models";

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
    setModel(ep.model ?? "");
    setApiKey("");
    setContextWindow(ep.contextWindow != null ? String(ep.contextWindow) : "");
    setNativeTools(ep.nativeTools);
    setVision(ep.vision);
    setThinking(ep.thinking);
    setFormOpen(true);
  };

  const valid = () => name().trim() !== "" && baseUrl().trim() !== "";

  const save = async () => {
    if (!valid() || saving()) return;
    setSaving(true);
    const cw = contextWindow().trim();
    const m = model().trim();
    const fields = {
      name: name().trim(),
      baseUrl: baseUrl().trim(),
      contextWindow: cw ? Number(cw) : null,
      nativeTools: nativeTools(),
      vision: vision(),
      thinking: thinking(),
    };
    try {
      const target = editing();
      if (target) {
        // Always send model so a cleared field unsets the default; the key is
        // only sent when typed (blank = leave the stored key unchanged).
        await updateEndpoint(target.id, {
          ...fields,
          model: m,
          ...(apiKey() ? { apiKey: apiKey() } : {}),
        });
        toast.success("Endpoint updated");
      } else {
        await createEndpoint({
          ...fields,
          model: m || undefined,
          apiKey: apiKey() || undefined,
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

  /* ── Role bindings ──────────────────────────────────────────────────────────
     A role binds to an ordered fallback chain (first = primary). The control
     below captures that order explicitly — membership *and* position — so it no
     longer rides on endpoint creation order. */
  const chainFor = (role: string): string[] => roles()?.[role] ?? [];
  const endpointName = (id: string): string =>
    (endpoints() ?? []).find((e) => e.id === id)?.name ?? id;
  const unboundFor = (role: string): ModelEndpoint[] => {
    const bound = new Set(chainFor(role));
    return (endpoints() ?? []).filter((e) => !bound.has(e.id));
  };

  const applyChain = async (role: string, next: string[]) => {
    try {
      await setRoleBinding(role, next);
    } catch {
      toast.error(`Unable to update the ${role} role.`);
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
        </Show>
      </Panel>

      <Panel label="ROLE BINDINGS">
        <Stack gap={4}>
          <Text variant="micro" tone="dim">
            Bind endpoints to each role as an ordered fallback chain (first =
            primary). `utility` runs background verification; `embedding` powers
            memory recall. The chat (`main`) model is chosen from the model
            picker in the top bar.
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
            label="DEFAULT MODEL (optional)"
            value={model()}
            onInput={(e) => setModel(e.currentTarget.value)}
            placeholder="qwen2.5-coder:32b"
            hint="Models are discovered from the provider and picked in the top bar. Set a default only as a fallback for providers without a models API."
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
