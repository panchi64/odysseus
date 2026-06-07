import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  Input,
  ListRow,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  confirm,
  toast,
  type Status,
} from "~/ui";
import { relativeTime, timestamp } from "~/lib/format";
import {
  useRagSources,
  useIndexStats,
  addRagSource,
  removeRagSource,
  restoreRagSource,
  createReindexController,
} from "../data";
import type { RagIndexStatus } from "../model";

const indexStatusFlag: Record<RagIndexStatus, Status> = {
  indexed: "nominal",
  indexing: "info",
  stale: "warn",
  error: "alert",
};

export function RagConfigScreen(): JSX.Element {
  const sources = useRagSources();
  const stats = useIndexStats();
  const [newPath, setNewPath] = createSignal("");
  const [rebuilding, setRebuilding] = createSignal(false);
  const [rebuildProgress, setRebuildProgress] = createSignal(0);

  const { reindexingIds, reindex } = createReindexController();

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  function startRebuild() {
    if (rebuilding()) return;
    setRebuilding(true);
    setRebuildProgress(0);
    const steps = [5, 12, 23, 38, 51, 64, 75, 87, 95, 100];
    steps.forEach((v, i) =>
      timers.push(
        setTimeout(
          () => {
            setRebuildProgress(v);
            if (v === 100)
              setTimeout(() => {
                setRebuilding(false);
                toast.success("Index rebuild complete");
              }, 600);
          },
          i * 500 + 300,
        ),
      ),
    );
  }

  function handleAddSource() {
    const path = newPath().trim();
    if (!path) return;
    addRagSource(path);
    setNewPath("");
    toast.success(`Source added — indexing started`, {
      duration: 5000,
    });
  }

  async function handleRemove(id: string, path: string, docCount: number) {
    const ok = await confirm({
      title: `Remove source?`,
      detail: `"${path}" (${docCount} docs) will be removed from the knowledge base. Indexed data will be lost and retrieval for dependent chats may degrade.`,
      confirmLabel: "REMOVE",
      tone: "alert",
    });
    if (!ok) return;
    const removed = removeRagSource(id);
    toast.success(`Source removed`, {
      action: removed
        ? {
            label: "UNDO",
            onClick: () => {
              restoreRagSource(removed);
              toast.info("Source restored");
            },
          }
        : undefined,
    });
  }

  function handleReindex(id: string, path: string) {
    reindex(id);
    toast.info(`Reindexing ${path}…`);
  }

  const errorSources = () => sources().filter((s) => s.status === "error");
  const healthySources = () =>
    sources().filter((s) => s.status !== "indexed" && s.status !== "indexing");

  return (
    <Stack gap={6}>
      <PageHeader
        title="KNOWLEDGE BASE"
        subtitle="RAG source collections and index configuration."
        assetId="ODY-RAG-01.0"
        actions={
          <Row gap={2}>
            <Show when={errorSources().length > 0}>
              <StatusFlag status="alert">{`${errorSources().length} ERROR`}</StatusFlag>
            </Show>
            <Button
              variant={rebuilding() ? "default" : "primary"}
              leading="refresh"
              onClick={startRebuild}
              disabled={rebuilding()}
            >
              {rebuilding() ? "REBUILDING..." : "REBUILD INDEX"}
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <InstrumentBand
          items={[
            {
              label: "TOTAL DOCS",
              value:
                stats()?.totalDocs != null ? String(stats()!.totalDocs) : "—",
            },
            {
              label: "COLLECTIONS",
              value: String(stats()?.totalCollections ?? "—"),
            },
            { label: "EMBEDDING MODEL", value: stats()?.embeddingModel ?? "—" },
            { label: "DIMS", value: String(stats()?.dims ?? "—") },
            { label: "STORE SIZE", value: stats()?.storeSize ?? "—" },
          ]}
        />
      </Suspense>

      <Show when={rebuilding()}>
        <Panel label="REBUILD IN PROGRESS">
          <ProgressBar
            value={rebuildProgress()}
            label={`INDEXING DOCUMENTS — ${rebuildProgress()}%`}
            tone="info"
            showValue
          />
        </Panel>
      </Show>

      <Panel label="INDEXED SOURCES" flush>
        <Show
          when={sources().length > 0}
          fallback={
            <EmptyState
              icon="database"
              message="NO SOURCES"
              hint="Add a folder path to start indexing."
            />
          }
        >
          <For each={sources()}>
            {(source) => (
              <ListRow
                label={source.path}
                leading="archive"
                right={
                  <span class="flex items-center gap-3 shrink-0">
                    <Text variant="micro" tone="dim">
                      {source.docCount} DOCS
                    </Text>
                    <Text variant="micro" tone="dim">
                      {relativeTime(source.lastIndexedAt)}
                    </Text>
                    <Show
                      when={reindexingIds().has(source.id)}
                      fallback={
                        <StatusFlag status={indexStatusFlag[source.status]}>
                          {source.status.toUpperCase()}
                        </StatusFlag>
                      }
                    >
                      <StatusFlag status="info">INDEXING…</StatusFlag>
                    </Show>
                    <Menu
                      trigger={
                        <span class="px-1 text-dim hover:text-bright">
                          <Text variant="micro">···</Text>
                        </span>
                      }
                      items={[
                        {
                          label: reindexingIds().has(source.id)
                            ? "REINDEXING…"
                            : "REINDEX",
                          icon: "refresh",
                          onSelect: () => handleReindex(source.id, source.path),
                        },
                        {
                          label: "VIEW DOCS",
                          icon: "library",
                          onSelect: () =>
                            toast.info("Document browser coming in Phase 2"),
                        },
                        {
                          label: "REMOVE",
                          icon: "trash",
                          danger: true,
                          onSelect: () =>
                            void handleRemove(
                              source.id,
                              source.path,
                              source.docCount,
                            ),
                        },
                      ]}
                    />
                  </span>
                }
              />
            )}
          </For>
        </Show>
      </Panel>

      {/* Add source */}
      <Panel label="ADD SOURCE">
        <Stack gap={3}>
          <Row gap={3} align="end">
            <div class="flex-1">
              <Input
                label="FOLDER PATH"
                placeholder="/home/user/documents"
                value={newPath()}
                onInput={(e) => setNewPath(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newPath().trim()) handleAddSource();
                }}
                type="text"
              />
            </div>
            <Button
              variant="primary"
              leading="plus"
              disabled={!newPath().trim()}
              onClick={handleAddSource}
            >
              ADD
            </Button>
          </Row>
          <Text variant="micro" tone="dim">
            Paths must be accessible to the Odysseus server process. The folder
            will be crawled and all supported file types indexed.
          </Text>
        </Stack>
      </Panel>

      {/* Index health */}
      <Show when={healthySources().length > 0}>
        <Panel label="INDEX HEALTH" state="alert">
          <Stack gap={2}>
            <Text variant="body" tone="warn">
              One or more sources are stale or unreachable. Retrieval quality
              may be degraded for affected collections.
            </Text>
            <For each={healthySources()}>
              {(source) => (
                <Row gap={2} align="center">
                  <StatusFlag status={indexStatusFlag[source.status]}>
                    {source.status.toUpperCase()}
                  </StatusFlag>
                  <Text variant="body" class="font-mono">
                    {source.path}
                  </Text>
                  <Text variant="micro" tone="dim">
                    last: {timestamp(source.lastIndexedAt)}
                  </Text>
                  <Show when={source.errorHint}>
                    <Text variant="micro" tone="alert">
                      {source.errorHint}
                    </Text>
                  </Show>
                  <Show when={source.status === "error"}>
                    <Tooltip label="Re-run indexing for this source" side="top">
                      <Button
                        variant="ghost"
                        leading="refresh"
                        onClick={() => handleReindex(source.id, source.path)}
                      >
                        RETRY
                      </Button>
                    </Tooltip>
                    <Button
                      variant="danger"
                      leading="trash"
                      onClick={() =>
                        void handleRemove(
                          source.id,
                          source.path,
                          source.docCount,
                        )
                      }
                    >
                      REMOVE
                    </Button>
                  </Show>
                </Row>
              )}
            </For>
          </Stack>
        </Panel>
      </Show>
    </Stack>
  );
}
