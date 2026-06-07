import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  confirm,
  EmptyState,
  Field,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  ProgressBar,
  Resource,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
} from "~/ui";
import { bytes, num, timestamp } from "~/lib/format";
import {
  cancelReindex,
  reindexSignal,
  startReindex,
  useEmbeddingModels,
  useIndexStats,
} from "../data";
import type { EmbeddingModel } from "../model";

export function EmbeddingScreen(): JSX.Element {
  const models = useEmbeddingModels();
  const stats = useIndexStats();
  const [activeId, setActiveId] = createSignal("all-minilm-l6-v2");

  const activeModel = () => (models() ?? []).find((m) => m.id === activeId());
  const reindex = reindexSignal;

  async function requestSwap(m: EmbeddingModel) {
    if (m.id === activeId()) return;
    const currentName = activeModel()?.name ?? activeId();
    const docCount = stats()?.indexedDocs ?? 0;

    const ok = await confirm({
      title: `Swap to ${m.name}?`,
      detail: `Swap from ${currentName} to ${m.name}? This requires re-indexing all ${num(docCount, 0)} documents. Retrieval will be degraded until the re-index completes.`,
      confirmLabel: "CONFIRM SWAP",
      cancelLabel: "CANCEL",
      tone: "alert",
    });

    if (!ok) return;

    setActiveId(m.id);
    startReindex(docCount);
    toast.info(`Re-indexing started — ${num(docCount, 0)} documents queued`);
  }

  function handleCancelReindex() {
    cancelReindex();
    toast.warn("Re-index cancelled — retrieval quality may be degraded");
  }

  const reindexProgress = () => {
    const s = reindex();
    if (!s) return 0;
    return Math.round((s.docsProcessed / s.totalDocs) * 100);
  };

  return (
    <Stack gap={6}>
      <PageHeader
        title="EMBEDDING MODELS"
        subtitle="Vector embedding configuration and index statistics."
        assetId="SYS-EMB-03.2"
        actions={
          <Show
            when={reindex()}
            fallback={
              <Show when={stats()?.requiresReindex}>
                <StatusFlag status="warn" dot>
                  REINDEX REQUIRED
                </StatusFlag>
              </Show>
            }
          >
            <StatusFlag status="info" dot>
              REINDEX IN PROGRESS
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
                {
                  label: "INDEXED DOCS",
                  value: reindex()
                    ? `${num(reindex()!.docsProcessed, 0)} / ${num(reindex()!.totalDocs, 0)}`
                    : String(s().indexedDocs),
                },
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

      <Show when={reindex()}>
        {(r) => (
          <Panel label="REINDEX IN PROGRESS">
            <Stack gap={3}>
              <ProgressBar
                value={reindexProgress()}
                label={`INDEXING DOCUMENTS — ${num(r().docsProcessed, 0)} / ${num(r().totalDocs, 0)} (${reindexProgress()}%)`}
                tone="info"
                showValue
              />
              <Show when={r().estimatedSecsRemaining > 0}>
                <Text variant="micro" tone="dim">
                  EST. TIME REMAINING: {r().estimatedSecsRemaining}S
                </Text>
              </Show>
              <Row gap={2}>
                <Button variant="ghost" onClick={handleCancelReindex}>
                  CANCEL REINDEX
                </Button>
              </Row>
            </Stack>
          </Panel>
        )}
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
          <Resource
            data={models}
            loadingLabel="LOADING MODELS"
            onRetry={models.refetch}
            errorMessage="FAILED TO LOAD MODELS"
            isEmpty={(v) => v.length === 0}
            emptyMessage="NO MODELS"
            empty={
              <div class="p-3">
                <EmptyState icon="database" message="NO MODELS" />
              </div>
            }
            loading={
              <div class="p-3">
                <LoadingText />
              </div>
            }
          >
            {(list) => (
              <For each={list()}>
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
            )}
          </Resource>
        </Panel>
      </div>
    </Stack>
  );
}
