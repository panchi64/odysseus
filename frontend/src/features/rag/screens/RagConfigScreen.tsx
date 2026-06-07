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
  type Status,
} from "~/ui";
import { relativeTime, timestamp } from "~/lib/format";
import { useIndexStats, useRagSources } from "../data";
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
            if (v === 100) setTimeout(() => setRebuilding(false), 600);
          },
          i * 500 + 300,
        ),
      ),
    );
  }

  const errorCount = () =>
    (sources() ?? []).filter((s) => s.status === "error").length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="KNOWLEDGE BASE"
        subtitle="RAG source collections and index configuration."
        assetId="ODY-RAG-01.0"
        actions={
          <Row gap={2}>
            <Show when={errorCount() > 0}>
              <StatusFlag status="alert">{`${errorCount()} ERROR`}</StatusFlag>
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
        <Suspense
          fallback={
            <div class="p-4">
              <LoadingText />
            </div>
          }
        >
          <Show
            when={(sources() ?? []).length}
            fallback={
              <EmptyState
                icon="database"
                message="NO SOURCES"
                hint="Add a folder path to start indexing."
              />
            }
          >
            <For each={sources() ?? []}>
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
                      <StatusFlag status={indexStatusFlag[source.status]}>
                        {source.status.toUpperCase()}
                      </StatusFlag>
                      <Menu
                        trigger={
                          <span class="px-1 text-dim hover:text-bright">
                            <Text variant="micro">···</Text>
                          </span>
                        }
                        items={[
                          {
                            label: "REINDEX",
                            icon: "refresh",
                            onSelect: () => {},
                          },
                          {
                            label: "VIEW DOCS",
                            icon: "library",
                            onSelect: () => {},
                          },
                          {
                            label: "REMOVE",
                            icon: "trash",
                            danger: true,
                            onSelect: () => {},
                          },
                        ]}
                      />
                    </span>
                  }
                />
              )}
            </For>
          </Show>
        </Suspense>
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
                type="text"
              />
            </div>
            <Button
              variant="primary"
              leading="plus"
              disabled={!newPath().trim()}
              onClick={() => setNewPath("")}
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
      <Show
        when={(sources() ?? []).some(
          (s) => s.status === "stale" || s.status === "error",
        )}
      >
        <Panel label="INDEX HEALTH" state="alert">
          <Stack gap={2}>
            <Text variant="body" tone="warn">
              One or more sources are stale or unreachable. Retrieval quality
              may be degraded for affected collections.
            </Text>
            <For
              each={(sources() ?? []).filter(
                (s) => s.status !== "indexed" && s.status !== "indexing",
              )}
            >
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
                </Row>
              )}
            </For>
          </Stack>
        </Panel>
      </Show>
    </Stack>
  );
}
