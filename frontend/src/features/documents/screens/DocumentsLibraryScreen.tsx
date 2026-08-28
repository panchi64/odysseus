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
import { useNavigate } from "@solidjs/router";
import { createListView } from "~/lib/list";
import { useTabParam } from "~/lib/useTabParam";
import { relativeTime } from "~/lib/format";
import {
  useDocuments,
  createDocument,
  deleteDocument,
  archiveDocument,
  unarchiveDocument,
  saveDocument,
} from "../data";
import { RenameDialog } from "../components/RenameDialog";
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
  const navigate = useNavigate();
  const docsResource = useDocuments();
  const documents = (): DocumentSummary[] => docsResource() ?? [];
  const [tab, setTab] = useTabParam<DocStatus>(
    "tab",
    ["active", "archived"],
    "active",
  );
  const [selectMode, setSelectMode] = createSignal(false);
  const [renaming, setRenaming] = createSignal<DocumentSummary | null>(null);

  const inTab = () => documents().filter((d) => d.status === tab());

  const view = createListView({
    source: inTab,
    search: (d) => `${d.title} ${d.snippet}`,
    sorts: {
      recent: {
        label: "Newest",
        compare: (a, b) => a.updatedAt.localeCompare(b.updatedAt),
      },
      name: {
        label: "Name",
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

  async function handleNew(): Promise<void> {
    try {
      const id = await createDocument("Untitled", "");
      navigate(`/documents/${id}`);
    } catch {
      toast.error("Could not create document");
    }
  }

  // Hard delete is irreversible (the confirm says so), so it carries no UNDO —
  // unlike archive below, which round-trips through the backend's restore.
  async function handleDelete(doc: DocumentSummary): Promise<void> {
    const ok = await confirm({
      title: `Delete "${doc.title}"?`,
      detail: "This action cannot be undone.",
      confirmLabel: "Delete",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteDocument(doc.id);
      toast.success(`Deleted "${doc.title}"`);
    } catch {
      toast.error(`Could not delete "${doc.title}"`);
    }
  }

  async function handleBulkDelete(): Promise<void> {
    const docs = view.selectedItems();
    if (!docs.length) return;
    const ok = await confirm({
      title: `Delete ${docs.length} document${docs.length > 1 ? "s" : ""}?`,
      detail: "This action cannot be undone.",
      confirmLabel: "Delete",
      tone: "alert",
    });
    if (!ok) return;
    // allSettled so one failure (e.g. a doc already removed elsewhere) doesn't abandon
    // the rest or swallow feedback — report whatever didn't delete.
    const results = await Promise.allSettled(
      docs.map((d) => deleteDocument(d.id)),
    );
    view.clearSelection();
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) {
      toast.error(`Could not delete ${failed} of ${docs.length} documents`);
    } else {
      toast.success(
        `Deleted ${docs.length} document${docs.length > 1 ? "s" : ""}`,
      );
    }
  }

  async function handleArchive(doc: DocumentSummary): Promise<void> {
    const toArchived = doc.status === "active";
    const apply = (archived: boolean) =>
      archived ? archiveDocument(doc.id) : unarchiveDocument(doc.id);
    try {
      await apply(toArchived);
    } catch {
      toast.error(
        `Could not ${toArchived ? "archive" : "restore"} "${doc.title}"`,
      );
      return;
    }
    toast.success(`${toArchived ? "Archived" : "Restored"} "${doc.title}"`, {
      action: {
        label: "Undo",
        onClick: () => {
          apply(!toArchived).catch(() => toast.error("Could not undo"));
        },
      },
    });
  }

  async function handleRename(id: string, title: string): Promise<void> {
    await saveDocument(id, { title });
    toast.success(`Renamed to "${title}"`);
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
        title="Documents"
        subtitle="Personal knowledge base and working notes."
        assetId="ODY-DOC-01.0"
        actions={
          <Button
            variant="primary"
            leading="plus"
            onClick={() => void handleNew()}
          >
            New document
          </Button>
        }
      />

      <InstrumentBand
        items={[
          { label: "Total", value: String(documents().length) },
          { label: "Active", value: String(totalActive()), tone: "nominal" },
          { label: "Archived", value: String(totalArchived()), tone: "dim" },
        ]}
      />

      <Panel flush>
        <div class="flex items-center gap-3 px-4 py-2">
          <Tabs
            items={[
              { value: "active", label: "Active" },
              { value: "archived", label: "Archived" },
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
            {selectMode() ? "Done" : "Select"}
          </Button>
        </div>

        <div class="p-3">
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
            allSelected={view.allSelected()}
            onToggleAll={selectMode() ? view.toggleAll : undefined}
            selectedCount={view.selectedCount()}
            onClearSelection={view.clearSelection}
            bulkActions={
              <Button
                variant="danger"
                size="sm"
                leading="trash"
                onClick={() => void handleBulkDelete()}
              >
                Delete
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
                    ? "No matches"
                    : tab() === "active"
                      ? "No active documents"
                      : "No archived documents"
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
                              label: "Rename",
                              icon: "pen",
                              onSelect: () => setRenaming(doc),
                            },
                            {
                              label:
                                doc.status === "active" ? "Archive" : "Restore",
                              icon: "archive",
                              onSelect: () => void handleArchive(doc),
                            },
                            {
                              label: "Delete",
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

      <RenameDialog
        open={renaming() !== null}
        currentTitle={renaming()?.title ?? ""}
        onClose={() => setRenaming(null)}
        onSubmit={(title) => handleRename(renaming()!.id, title)}
      />
    </Stack>
  );
}
