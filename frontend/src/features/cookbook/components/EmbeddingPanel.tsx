import { createMemo, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  confirm,
  EmptyState,
  Field,
  InstrumentBand,
  ListRow,
  LoadingText,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { useEndpoints } from "~/lib/stores/models";
import { useManagedModels } from "../serving";
import { useManagedModelActions } from "../serving-actions";
import {
  setEmbeddingRole,
  triggerReindex,
  useEmbeddingRole,
  useReindexStatus,
} from "../embedding/data";
import type { ReindexState } from "../embedding/model";
import type { ManagedModel } from "../model";

const STATE_STATUS: Record<
  ReindexState,
  "nominal" | "warn" | "info" | "alert"
> = {
  idle: "nominal",
  running: "info",
  done: "nominal",
  degraded: "warn",
  error: "alert",
};

/** Vector-embedding configuration and reindex status — the EMBEDDING tab of the
 *  Model Cookbook. Owns no page chrome; the Cookbook screen provides the header.
 *  The servable catalog is the same managed-models list `EmbeddingServePanel`
 *  renders (there's no curated remote catalog on the backend); this panel adds
 *  which one is bound to the `embedding` role and the reindex job's state. */
export function EmbeddingPanel(): JSX.Element {
  const role = useEmbeddingRole();
  const reindex = useReindexStatus();
  const endpoints = useEndpoints();
  const managed = useManagedModels();
  const actions = useManagedModelActions(managed);

  const embeddingModels = createMemo(() =>
    managed.models().filter((m) => m.workload === "embedding"),
  );
  const activeEndpointId = () => role()?.endpointId ?? null;
  const activeManaged = createMemo(() =>
    embeddingModels().find((m) => m.endpointId === activeEndpointId()),
  );
  const activeEndpointName = () =>
    (endpoints() ?? []).find((e) => e.id === activeEndpointId())?.name;

  async function requestSwap(m: ManagedModel) {
    if (m.endpointId === activeEndpointId()) return;
    const ok = await confirm({
      title: `Swap to ${m.hfRepo}?`,
      detail: `Bind the embedding role to ${m.hfRepo}? Existing memories and chat history re-index into its vector space in the background — recall degrades to keyword-only until it finishes.`,
      confirmLabel: "CONFIRM SWAP",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok || !m.endpointId) return;
    try {
      await setEmbeddingRole(m.endpointId, null);
      toast.success(`Embedding role bound to ${m.hfRepo}`);
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to switch the embedding model.",
      );
    } finally {
      role.refetch();
      reindex.refetch();
    }
  }

  async function handleReindexNow() {
    try {
      await triggerReindex();
      toast.info("Reindex started");
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Unable to start the reindex.",
      );
    } finally {
      reindex.refetch();
    }
  }

  return (
    <Stack gap={6}>
      <Row gap={3} align="start" justify="between">
        <Text variant="micro" tone="dim" class="flex-1">
          Embeddings turn documents into vectors so the agent can search by
          meaning. Binding a different model re-indexes the whole library in the
          background — until that finishes, recall falls back to keyword
          matching.
        </Text>
        <Show when={reindex()}>
          {(r) => (
            <StatusFlag
              status={STATE_STATUS[r().state]}
              dot={r().state === "running"}
            >
              {`REINDEX ${r().state.toUpperCase()}`}
            </StatusFlag>
          )}
        </Show>
      </Row>

      <Suspense fallback={<LoadingText label="LOADING STATS" />}>
        <Show when={reindex()}>
          {(r) => (
            <InstrumentBand
              items={[
                {
                  label: "ACTIVE MODEL",
                  value: activeManaged()?.hfRepo ?? activeEndpointName() ?? "—",
                },
                { label: "STATE", value: r().state.toUpperCase() },
                { label: "MEMORIES INDEXED", value: String(r().memories) },
                { label: "MESSAGES INDEXED", value: String(r().messages) },
                {
                  label: "LAST REINDEX",
                  value: r().completedAt ? timestamp(r().completedAt!) : "—",
                },
              ]}
            />
          )}
        </Show>
      </Suspense>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel label="ACTIVE MODEL" class="lg:col-span-1">
          <Suspense fallback={<LoadingText />}>
            <Show
              when={activeEndpointId()}
              fallback={
                <Text variant="micro" tone="dim">
                  No embedding model bound yet — recall runs keyword-only.
                </Text>
              }
            >
              <Stack gap={3}>
                <Field
                  label="MODEL"
                  value={activeManaged()?.hfRepo ?? role()?.model ?? "default"}
                />
                <Field label="ENDPOINT" value={activeEndpointName() ?? "—"} />
                <Show when={activeManaged()}>
                  {(m) => (
                    <>
                      <Field label="ENGINE" value={m().engine} />
                      <Show when={m().quant}>
                        <Field label="QUANT" value={m().quant!} />
                      </Show>
                    </>
                  )}
                </Show>
              </Stack>
            </Show>
          </Suspense>
        </Panel>

        <Panel
          label="SERVED EMBEDDING MODELS"
          meta={
            <Text variant="micro" tone="dim">
              SELECT TO ACTIVATE
            </Text>
          }
          flush
          class="lg:col-span-2"
        >
          <Show
            when={!managed.loading()}
            fallback={
              <div class="p-3">
                <LoadingText label="LOADING MODELS" />
              </div>
            }
          >
            <Show
              when={embeddingModels().length > 0}
              fallback={
                <div class="p-3">
                  <EmptyState
                    icon="database"
                    message="NO EMBEDDING MODELS SERVED"
                  />
                </div>
              }
            >
              <Stack gap={0}>
                <For each={embeddingModels()}>
                  {(m) => (
                    <ListRow
                      label={m.hfRepo}
                      leading="database"
                      selected={m.endpointId === activeEndpointId()}
                      right={
                        <Row gap={2} align="center">
                          <Text variant="micro" tone="dim">
                            {m.engine}
                          </Text>
                          <StatusFlag
                            status={m.state === "running" ? "nominal" : "warn"}
                          >
                            {m.state.toUpperCase()}
                          </StatusFlag>
                          <Show
                            when={
                              m.state === "running" &&
                              m.endpointId !== activeEndpointId()
                            }
                          >
                            <Button
                              size="sm"
                              variant="default"
                              onClick={() => requestSwap(m)}
                            >
                              SET ACTIVE
                            </Button>
                          </Show>
                          <Show when={m.endpointId === activeEndpointId()}>
                            <StatusFlag status="nominal">ACTIVE</StatusFlag>
                          </Show>
                          <Show
                            when={m.state === "running"}
                            fallback={
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() =>
                                  actions.serve({
                                    engine: m.engine,
                                    repo: m.hfRepo,
                                    role: "embedding",
                                    workload: "embedding",
                                    quant: m.quant ?? undefined,
                                  })
                                }
                              >
                                SERVE
                              </Button>
                            }
                          >
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => actions.stop(m)}
                            >
                              STOP
                            </Button>
                          </Show>
                        </Row>
                      }
                    />
                  )}
                </For>
              </Stack>
            </Show>
          </Show>
        </Panel>
      </div>

      <Row gap={2}>
        <Button
          variant="ghost"
          onClick={handleReindexNow}
          disabled={reindex()?.state === "running"}
        >
          REINDEX NOW
        </Button>
      </Row>
    </Stack>
  );
}
