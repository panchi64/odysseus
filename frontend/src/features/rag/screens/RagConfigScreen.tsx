import {
  createEffect,
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { useNavigate } from "@solidjs/router";
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
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  confirm,
  toast,
  type MenuItem,
  type Status,
} from "~/ui";
import { isApiError } from "~/lib/api";
import { relativeTime, timestamp } from "~/lib/format";
import {
  useRagSources,
  useIndexStats,
  refreshCorpus,
  addRagSource,
  removeRagSource,
  reindexSource,
  rebuildAllFolders,
} from "../data";
import type { RagIndexStatus, RagSource } from "../model";

const indexStatusFlag: Record<RagIndexStatus, Status> = {
  indexed: "nominal",
  indexing: "info",
  stale: "warn",
  error: "alert",
};

/** Surface a failed backend action without leaking raw errors. */
function reportError(fallback: string, err: unknown): void {
  toast.error(isApiError(err) ? err.detail : fallback);
}

export function RagConfigScreen(): JSX.Element {
  const navigate = useNavigate();
  const sources = useRagSources();
  const stats = useIndexStats();
  const [newPath, setNewPath] = createSignal("");
  const [rebuilding, setRebuilding] = createSignal(false);

  const all = (): RagSource[] => sources() ?? [];
  const surfaces = () => all().filter((s) => s.kind === "surface");
  const folders = () => all().filter((s) => s.kind === "folder");
  const errorSources = () => all().filter((s) => s.status === "error");
  const degradedSources = () =>
    all().filter((s) => s.status === "stale" || s.status === "error");
  const anyIndexing = () => all().some((s) => s.status === "indexing");

  // Indexing runs server-side off the request path; poll the source list while any
  // source is mid-index so its status flips here when the backend finishes. The timer
  // lives in this consuming layer, not the data seam.
  createEffect(() => {
    if (!anyIndexing()) return;
    const timer = setInterval(refreshCorpus, 1500);
    onCleanup(() => clearInterval(timer));
  });

  async function startRebuild() {
    if (rebuilding()) return;
    setRebuilding(true);
    try {
      await rebuildAllFolders(all());
      toast.success("Rebuild started");
    } catch (err) {
      reportError("Rebuild failed", err);
    } finally {
      setRebuilding(false);
    }
  }

  async function handleAddSource() {
    const path = newPath().trim();
    if (!path) return;
    try {
      await addRagSource(path);
      setNewPath("");
      toast.success("Source added — indexing started", { duration: 5000 });
    } catch (err) {
      reportError("Could not add source", err);
    }
  }

  async function handleRemove(id: string, label: string, docCount: number) {
    const ok = await confirm({
      title: `Remove source?`,
      detail: `"${label}" (${docCount} docs) will be removed from the knowledge base. Indexed data will be lost and retrieval for dependent chats may degrade.`,
      confirmLabel: "REMOVE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await removeRagSource(id);
      toast.success("Source removed", {
        action: {
          label: "UNDO",
          onClick: () => {
            void addRagSource(label)
              .then(() => toast.info("Source restored — reindexing"))
              .catch((err) => reportError("Could not restore source", err));
          },
        },
      });
    } catch (err) {
      reportError("Could not remove source", err);
    }
  }

  async function handleReindex(id: string, label: string) {
    try {
      await reindexSource(id);
      toast.info(`Reindexing ${label}…`);
    } catch (err) {
      reportError("Could not reindex", err);
    }
  }

  /** One indexed-source row, shared by both the surfaces and folders panels —
   *  the only difference is the menu actions each kind supports. */
  function sourceRow(source: RagSource): JSX.Element {
    const menuItems: MenuItem[] =
      source.kind === "surface"
        ? [
            {
              label: "OPEN",
              icon: "arrow-right",
              onSelect: () => {
                if (source.href) navigate(source.href);
              },
            },
            {
              label: "REINDEX",
              icon: "refresh",
              onSelect: () => void handleReindex(source.id, source.label),
            },
          ]
        : [
            {
              label: "REINDEX",
              icon: "refresh",
              onSelect: () => void handleReindex(source.id, source.label),
            },
            {
              label: "VIEW DOCS",
              icon: "library",
              onSelect: () => toast.info("Document browser coming in Phase 2"),
            },
            {
              label: "REMOVE",
              icon: "trash",
              danger: true,
              onSelect: () =>
                void handleRemove(source.id, source.label, source.docCount),
            },
          ];

    return (
      <ListRow
        label={source.label}
        leading={source.icon}
        right={
          <span class="flex items-center gap-3 shrink-0">
            <Text variant="micro" tone="dim">
              {source.docCount} DOCS
            </Text>
            <Text variant="micro" tone="dim">
              {source.lastIndexedAt ? relativeTime(source.lastIndexedAt) : "—"}
            </Text>
            <StatusFlag status={indexStatusFlag[source.status]}>
              {source.status === "indexing"
                ? "INDEXING…"
                : source.status.toUpperCase()}
            </StatusFlag>
            <Menu
              trigger={
                <span class="px-1 text-dim hover:text-bright">
                  <Text variant="micro">···</Text>
                </span>
              }
              items={menuItems}
            />
          </span>
        }
      />
    );
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="KNOWLEDGE BASE"
        subtitle="The unified retrieval corpus — every source the assistant can search."
        assetId="ODY-RAG-01.0"
        actions={
          <Row gap={2}>
            <Show when={errorSources().length > 0}>
              <StatusFlag status="alert">{`${errorSources().length} ERROR`}</StatusFlag>
            </Show>
            <Button
              variant={rebuilding() ? "default" : "primary"}
              leading="refresh"
              onClick={() => void startRebuild()}
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

      <Suspense fallback={<LoadingText />}>
        <Panel label="CORPUS SURFACES" flush>
          <Show
            when={surfaces().length > 0}
            fallback={
              <EmptyState
                icon="library"
                message="NO SURFACES"
                hint="Documents, uploads, gallery, memory and research index here automatically."
              />
            }
          >
            <For each={surfaces()}>{(source) => sourceRow(source)}</For>
          </Show>
        </Panel>

        <Panel label="INDEXED FOLDERS" flush>
          <Show
            when={folders().length > 0}
            fallback={
              <EmptyState
                icon="archive"
                message="NO FOLDERS"
                hint="Add a host folder path below to start indexing."
              />
            }
          >
            <For each={folders()}>{(source) => sourceRow(source)}</For>
          </Show>
        </Panel>
      </Suspense>

      {/* Add folder source */}
      <Panel label="ADD FOLDER">
        <Stack gap={3}>
          <Row gap={3} align="end">
            <div class="flex-1">
              <Input
                label="FOLDER PATH"
                placeholder="/home/user/documents"
                value={newPath()}
                onInput={(e) => setNewPath(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newPath().trim())
                    void handleAddSource();
                }}
                type="text"
              />
            </div>
            <Button
              variant="primary"
              leading="plus"
              disabled={!newPath().trim()}
              onClick={() => void handleAddSource()}
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
      <Show when={degradedSources().length > 0}>
        <Panel label="INDEX HEALTH" state="alert">
          <Stack gap={2}>
            <Text variant="body" tone="warn">
              One or more sources are stale or unreachable. Retrieval quality
              may be degraded for affected collections.
            </Text>
            <For each={degradedSources()}>
              {(source) => (
                <Row gap={2} align="center">
                  <StatusFlag status={indexStatusFlag[source.status]}>
                    {source.status.toUpperCase()}
                  </StatusFlag>
                  <Text variant="body" class="font-mono">
                    {source.label}
                  </Text>
                  <Text variant="micro" tone="dim">
                    last:{" "}
                    {source.lastIndexedAt
                      ? timestamp(source.lastIndexedAt)
                      : "—"}
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
                        onClick={() =>
                          void handleReindex(source.id, source.label)
                        }
                      >
                        RETRY
                      </Button>
                    </Tooltip>
                    <Show when={source.kind === "folder"}>
                      <Button
                        variant="danger"
                        leading="trash"
                        onClick={() =>
                          void handleRemove(
                            source.id,
                            source.label,
                            source.docCount,
                          )
                        }
                      >
                        REMOVE
                      </Button>
                    </Show>
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
