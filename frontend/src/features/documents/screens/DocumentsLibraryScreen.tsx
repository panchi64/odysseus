import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListRow,
  ListToolbar,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  confirm,
  toast,
  type Status,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import {
  useDocumentList,
  deleteDocument,
  restoreDocument,
  toggleArchiveDocument,
} from "../data";
import type { DocStatus, DocumentSummary } from "../model";

const statusMap: Record<DocStatus, Status> = {
  active: "nominal",
  archived: "idle",
};

function WordCount(props: { words: number }): JSX.Element {
  return (
    <Text variant="micro" tone="dim">
      {props.words.toLocaleString()} W
    </Text>
  );
}

export function DocumentsLibraryScreen(): JSX.Element {
  const documents = useDocumentList();
  const [tab, setTab] = createSignal<DocStatus>("active");
  const [selectMode, setSelectMode] = createSignal(false);

  const inTab = () => documents().filter((d) => d.status === tab());

  const view = createListView({
    source: inTab,
    search: (d) => `${d.title} ${d.snippet}`,
    sorts: {
      recent: {
        label: "NEWEST",
        compare: (a, b) => a.updatedAt.localeCompare(b.updatedAt),
      },
      name: {
        label: "NAME",
        compare: (a, b) => a.title.localeCompare(b.title),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
    id: (d) => d.id,
  });

  const totalActive = () =>
    documents().filter((d) => d.status === "active").length;
  const totalArchived = () =>
    documents().filter((d) => d.status === "archived").length;

  async function handleDelete(doc: DocumentSummary): Promise<void> {
    const ok = await confirm({
      title: `Delete "${doc.title}"?`,
      detail: "This action cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    deleteDocument(doc.id);
    toast.success(`Deleted "${doc.title}"`, {
      action: {
        label: "UNDO",
        onClick: () => restoreDocument(doc),
      },
    });
  }

  async function handleBulkDelete(): Promise<void> {
    const docs = view.selectedItems();
    if (!docs.length) return;
    const ok = await confirm({
      title: `Delete ${docs.length} document${docs.length > 1 ? "s" : ""}?`,
      detail: "This action cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    docs.forEach((d) => deleteDocument(d.id));
    view.clearSelection();
    toast.success(
      `Deleted ${docs.length} document${docs.length > 1 ? "s" : ""}`,
      {
        action: {
          label: "UNDO",
          onClick: () => docs.forEach((d) => restoreDocument(d)),
        },
      },
    );
  }

  function handleArchive(doc: DocumentSummary): void {
    const next: DocStatus = doc.status === "active" ? "archived" : "active";
    const prev: DocStatus = doc.status;
    toggleArchiveDocument(doc.id, next);
    const label = next === "archived" ? "Archived" : "Restored";
    toast.success(`${label} "${doc.title}"`, {
      action: {
        label: "UNDO",
        onClick: () => toggleArchiveDocument(doc.id, prev),
      },
    });
  }

  function toggleSelectMode(): void {
    setSelectMode((on) => {
      if (on) view.clearSelection();
      return !on;
    });
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="DOCUMENTS"
        subtitle="Personal knowledge base and working notes."
        assetId="ODY-DOC-01.0"
        actions={
          <Button variant="primary" leading="plus">
            NEW DOCUMENT
          </Button>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String(documents().length) },
          { label: "ACTIVE", value: String(totalActive()), tone: "nominal" },
          { label: "ARCHIVED", value: String(totalArchived()), tone: "dim" },
        ]}
      />

      <Panel flush>
        <div class="flex items-center gap-3 border-b border-line px-4 py-2">
          <Tabs
            items={[
              { value: "active", label: "ACTIVE" },
              { value: "archived", label: "ARCHIVED" },
            ]}
            value={tab()}
            onChange={(v) => setTab(v as DocStatus)}
            class="flex-1"
          />
          <Button
            variant={selectMode() ? "primary" : "ghost"}
            size="sm"
            leading="check"
            onClick={toggleSelectMode}
          >
            {selectMode() ? "DONE" : "SELECT"}
          </Button>
        </div>

        <div class="border-b border-line p-3">
          <ListToolbar
            query={view.query()}
            onQueryChange={view.setQuery}
            placeholder="Search documents…"
            sortKey={view.sortKey()}
            sortOptions={view.sortOptions}
            onSortChange={view.setSort}
            dir={view.dir()}
            onToggleDir={view.toggleDir}
            count={view.count()}
            total={view.total()}
            selectedCount={view.selectedCount()}
            onClearSelection={view.clearSelection}
            bulkActions={
              <Button
                variant="danger"
                size="sm"
                leading="trash"
                onClick={() => void handleBulkDelete()}
              >
                DELETE
              </Button>
            }
          />
        </div>

        <Suspense
          fallback={
            <div class="p-4">
              <LoadingText />
            </div>
          }
        >
          <Show
            when={view.items().length}
            fallback={
              <EmptyState
                icon="file"
                message={
                  view.isFiltered()
                    ? "NO MATCHES"
                    : tab() === "active"
                      ? "NO ACTIVE DOCUMENTS"
                      : "NO ARCHIVED DOCUMENTS"
                }
                hint={
                  view.isFiltered()
                    ? "No documents match your search."
                    : tab() === "active"
                      ? "Create a document to get started."
                      : "Archived documents appear here."
                }
              />
            }
          >
            <For each={view.items()}>
              {(doc) => (
                <ListRow
                  label={doc.title}
                  leading="file"
                  selectable={selectMode()}
                  selected={selectMode() && view.isSelected(doc.id)}
                  href={selectMode() ? undefined : `/documents/${doc.id}`}
                  onClick={
                    selectMode() ? () => view.toggleOne(doc.id) : undefined
                  }
                  right={
                    <span class="flex items-center gap-3">
                      <WordCount words={doc.words} />
                      <Text variant="micro" tone="dim">
                        {relativeTime(doc.updatedAt)}
                      </Text>
                      <StatusFlag status={statusMap[doc.status]}>
                        {doc.status.toUpperCase()}
                      </StatusFlag>
                      <Show when={!selectMode()}>
                        <Menu
                          trigger={
                            <span class="px-1 text-dim hover:text-bright">
                              <Text variant="micro">···</Text>
                            </span>
                          }
                          items={[
                            {
                              label:
                                doc.status === "active" ? "ARCHIVE" : "RESTORE",
                              icon: "archive",
                              onSelect: () => handleArchive(doc),
                            },
                            {
                              label: "DELETE",
                              icon: "trash",
                              danger: true,
                              onSelect: () => void handleDelete(doc),
                            },
                          ]}
                        />
                      </Show>
                    </span>
                  }
                />
              )}
            </For>
          </Show>
        </Suspense>
      </Panel>
    </Stack>
  );
}
