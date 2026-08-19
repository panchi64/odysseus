import { createMemo, For, Show, type JSX } from "solid-js";
import {
  Button,
  Panel,
  Row,
  Select,
  type SelectOption,
  Stack,
  StatusDot,
  StatusFlag,
  Text,
  toast,
} from "~/ui";
import { isApiError } from "~/lib/api";
import { setRoleBinding, useEndpoints, useRoles } from "../data";
import { BINDABLE_ROLES } from "../model";
import { EmbeddingRoleControls } from "./EmbeddingRoleControls";
import { healthStatus } from "./EndpointHealthFlag";
import { modelGroups, type ModelEndpoint } from "~/lib/stores/models";

/* A role binds to an ordered fallback chain (first = primary). The control
   below captures that order explicitly — membership *and* position — so it no
   longer rides on endpoint creation order. */
export function RoleBindingsSection(): JSX.Element {
  const endpoints = useEndpoints();
  const roles = useRoles();

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

  // The models a role's primary (head) endpoint serves, plus an explicit "endpoint
  // default" choice and the current pick (so it stays selectable even if discovery
  // missed it). The backend pins this model on the head endpoint, so a
  // discovery-only provider (no default model) becomes resolvable — the same fact
  // research/tasks/titling depend on. Shared by main, utility, and embedding.
  const roleModelOptions = (role: string): SelectOption[] => {
    const opts: SelectOption[] = [{ value: "", label: "ENDPOINT DEFAULT" }];
    const primary = chainFor(role)[0];
    const models = primary
      ? (
          modelGroups().find((g) => g.endpointId === primary)?.choices ?? []
        ).map((c) => c.model)
      : [];
    for (const m of models) opts.push({ value: m, label: m });
    const current = modelFor(role);
    if (current && !models.includes(current))
      opts.push({ value: current, label: current });
    return opts;
  };
  const embeddingModelOptions = createMemo<SelectOption[]>(() =>
    roleModelOptions("embedding"),
  );

  // `main` is single-endpoint (the top-bar picker overwrites the whole binding), so
  // Settings edits it as one provider, not a chain. Only tool-calling endpoints are
  // offered — the backend rejects the rest on bind.
  const mainEndpointOptions = (): SelectOption[] => [
    { value: "", label: "NONE" },
    ...(endpoints() ?? [])
      .filter((e) => e.enabled && e.nativeTools)
      .map((e) => ({ value: e.id, label: e.name })),
  ];

  // Re-bind preserves the role's pinned model unless a new one is given; a backend
  // rejection (e.g. a non-embeddings model) surfaces its detail to the operator.
  // The store's role write re-reads the shared bindings, so a `main` write already
  // refreshes the top-bar picker — both read the one binding.
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
  // Switching main's endpoint clears the old pin (a model on the prior provider
  // rarely exists on the new one); the operator then picks a model below.
  const setMainEndpoint = (id: string) =>
    applyChain("main", id ? [id] : [], null);
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

  return (
    <Panel label="ROLE BINDINGS">
      <Stack gap={4}>
        <Text variant="micro" tone="dim">
          `main` is the chat model — also used by research, tasks, and titling —
          and is single-endpoint (the same binding the top-bar picker writes).
          `utility` runs background verification; `embedding` powers memory
          recall — both bind an ordered fallback chain (first = primary) and
          auto-switch past dead/disabled endpoints. A pinned model lets a
          discovery-only provider (no default) be used.
        </Text>
        <Show
          when={(endpoints() ?? []).length}
          fallback={
            <Text variant="micro" tone="dim">
              Add an endpoint to bind roles.
            </Text>
          }
        >
          <Stack gap={2}>
            <Text variant="label" tone="bright">
              MAIN
            </Text>
            <Select
              label="ENDPOINT"
              value={chainFor("main")[0] ?? ""}
              options={mainEndpointOptions()}
              onChange={setMainEndpoint}
              hint="The chat model. Also drives research, tasks, and titling."
            />
            <Show when={chainFor("main").length > 0}>
              <Select
                label="MODEL"
                value={modelFor("main") ?? ""}
                options={roleModelOptions("main")}
                onChange={(v) =>
                  void applyChain("main", chainFor("main"), v === "" ? null : v)
                }
                hint="Pin a model — required for a provider that serves no default."
              />
            </Show>
          </Stack>
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
                              <StatusFlag status="nominal">PRIMARY</StatusFlag>
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
                <Show
                  when={role === "utility" && chainFor("utility").length > 0}
                >
                  <Select
                    label="MODEL"
                    value={modelFor("utility") ?? ""}
                    options={roleModelOptions("utility")}
                    onChange={(v) =>
                      void applyChain(
                        "utility",
                        chainFor("utility"),
                        v === "" ? null : v,
                      )
                    }
                    hint="The model on the primary endpoint — pin one for a provider with no default."
                  />
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
  );
}
