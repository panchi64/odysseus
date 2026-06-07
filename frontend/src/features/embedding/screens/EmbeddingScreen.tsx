import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  Field,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import { bytes, num, timestamp } from "~/lib/format";
import { useEmbeddingModels, useIndexStats } from "../data";
import type { EmbeddingModel } from "../model";

export function EmbeddingScreen(): JSX.Element {
  const models = useEmbeddingModels();
  const stats = useIndexStats();
  const [activeId, setActiveId] = createSignal("all-minilm-l6-v2");
  const [pendingId, setPendingId] = createSignal<string | null>(null);
  const [confirmOpen, setConfirmOpen] = createSignal(false);

  const activeModel = () => (models() ?? []).find((m) => m.id === activeId());

  function requestSwap(m: EmbeddingModel) {
    if (m.id === activeId()) return;
    setPendingId(m.id);
    setConfirmOpen(true);
  }

  function confirmSwap() {
    if (pendingId()) setActiveId(pendingId()!);
    setPendingId(null);
    setConfirmOpen(false);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="EMBEDDING MODELS"
        subtitle="Vector embedding configuration and index statistics."
        assetId="SYS-EMB-03.2"
        actions={
          <Show when={stats()?.requiresReindex}>
            <StatusFlag status="warn" dot>
              REINDEX REQUIRED
            </StatusFlag>
          </Show>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING STATS" />}>
        <Show when={stats()}>
          {(s) => (
            <InstrumentBand
              items={[
                { label: "ACTIVE MODEL", value: activeModel()?.name ?? "—" },
                { label: "DIMS", value: String(s().dims) },
                { label: "INDEXED DOCS", value: String(s().indexedDocs) },
                {
                  label: "THROUGHPUT",
                  value: `${num(s().throughputDocsSec, 0)} DOC/S`,
                },
                { label: "LAST INDEXED", value: timestamp(s().lastIndexedAt) },
                {
                  label: "PROVIDER",
                  value: activeModel()?.provider.toUpperCase() ?? "—",
                },
              ]}
            />
          )}
        </Show>
      </Suspense>

      <Show when={confirmOpen()}>
        <Panel label="CONFIRM MODEL SWAP" state="alert">
          <Stack gap={4}>
            <Text variant="body" tone="warn">
              Swapping the active embedding model requires a full re-index of
              all {stats()?.indexedDocs ?? "?"} documents. Retrieval will be
              degraded until the re-index completes.
            </Text>
            <Row gap={2}>
              <Button variant="danger" onClick={confirmSwap}>
                CONFIRM SWAP
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setConfirmOpen(false);
                  setPendingId(null);
                }}
              >
                CANCEL
              </Button>
            </Row>
          </Stack>
        </Panel>
      </Show>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel label="ACTIVE MODEL" class="lg:col-span-1">
          <Suspense fallback={<LoadingText />}>
            <Show when={activeModel()}>
              {(m) => (
                <Stack gap={3}>
                  <Field label="NAME" value={m().name} />
                  <Field label="DIMS" value={String(m().dims)} />
                  <Field label="PROVIDER" value={m().provider.toUpperCase()} />
                  <Show when={m().sizeBytes}>
                    <Field label="SIZE" value={bytes(m().sizeBytes!)} />
                  </Show>
                  <Show when={m().description}>
                    <Text variant="micro" tone="dim">
                      {m().description}
                    </Text>
                  </Show>
                </Stack>
              )}
            </Show>
          </Suspense>
        </Panel>

        <Panel
          label="AVAILABLE MODELS"
          meta={
            <Text variant="micro" tone="dim">
              SELECT TO ACTIVATE
            </Text>
          }
          flush
          class="lg:col-span-2"
        >
          <Suspense
            fallback={
              <div class="p-3">
                <LoadingText />
              </div>
            }
          >
            <Show
              when={(models() ?? []).length}
              fallback={<EmptyState icon="database" message="NO MODELS" />}
            >
              <For each={models()}>
                {(m) => (
                  <ListRow
                    label={m.name}
                    leading="database"
                    selected={m.id === activeId()}
                    right={
                      <Row gap={2} align="center">
                        <Text variant="micro" tone="dim">
                          {m.dims}D
                        </Text>
                        <Show when={m.sizeBytes}>
                          <Text variant="micro" tone="dim">
                            {bytes(m.sizeBytes!)}
                          </Text>
                        </Show>
                        <StatusFlag
                          status={m.provider === "local" ? "nominal" : "info"}
                        >
                          {m.provider.toUpperCase()}
                        </StatusFlag>
                        <Show
                          when={m.id !== activeId()}
                          fallback={
                            <StatusFlag status="nominal">ACTIVE</StatusFlag>
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
                      </Row>
                    }
                  />
                )}
              </For>
            </Show>
          </Suspense>
        </Panel>
      </div>
    </Stack>
  );
}
