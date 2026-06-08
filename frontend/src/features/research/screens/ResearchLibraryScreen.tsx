import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { produce } from "solid-js/store";
import {
  Button,
  confirm,
  EmptyState,
  ErrorState,
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
  toast,
  type Status,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import {
  useReportSummaries,
  createResearchRun,
  useSummariesStore,
} from "../data";
import { RunPanel } from "../components/RunPanel";
import type { ResearchStatus, ResearchSummary } from "../model";

const statusMap: Record<ResearchStatus, Status> = {
  complete: "nominal",
  running: "info",
  archived: "idle",
  error: "alert",
};

/** Research library + run hub. Two-tab layout: RUN and LIBRARY. */
export function ResearchLibraryScreen(): JSX.Element {
  const [tab, setTab] = createSignal<string>("run");
  const summariesResource = useReportSummaries();
  const [store, setStore] = useSummariesStore();
  const { running, state, run } = createResearchRun();

  // Seed the mutable store from the resource once loaded (idempotent after first call)
  const summaries = () => store.list;

  const view = createListView({
    source: summaries,
    search: (r) => r.title,
    sorts: {
      recent: {
        label: "DATE",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
      status: {
        label: "STATUS",
        compare: (a, b) => a.status.localeCompare(b.status),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
  });

  async function handleArchive(r: ResearchSummary) {
    if (r.status === "archived") {
      toast.info(`"${r.title}" is already archived.`);
      return;
    }
    setStore(
      "list",
      (item) => item.id === r.id,
      produce((item) => {
        item.status = "archived";
      }),
    );
    toast.success(`Archived — ${r.title}`);
  }

  async function handleDelete(r: ResearchSummary) {
    const ok = await confirm({
      title: `Delete "${r.title}"?`,
      detail:
        "This research report and all its sources will be permanently removed. This cannot be undone.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;

    const deleted = r;
    setStore("list", (list) => list.filter((item) => item.id !== r.id));
    toast.success(`Deleted — ${deleted.title}`, {
      action: {
        label: "UNDO",
        onClick: () => {
          setStore("list", (list) => [deleted, ...list]);
          toast.success("Delete undone.");
        },
      },
    });
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="DEEP RESEARCH"
        subtitle="Multi-round synthesis engine. Plan → search → read → analyze → write."
        assetId="ODY-RES-01.0"
        actions={
          <StatusFlag status={running() ? "info" : "idle"} dot={running()}>
            {running() ? "RUNNING" : "IDLE"}
          </StatusFlag>
        }
      />

      <Tabs
        items={[
          { value: "run", label: "RUN" },
          { value: "library", label: "LIBRARY" },
        ]}
        value={tab()}
        onChange={setTab}
      />

      <Show when={tab() === "run"}>
        <RunPanel running={running()} state={state} onRun={run} />
      </Show>

      <Show when={tab() === "library"}>
        <Panel label="RESEARCH REPORTS" flush>
          <div class="border-b border-line p-3">
            <ListToolbar
              query={view.query()}
              onQueryChange={view.setQuery}
              placeholder="Search reports by title…"
              sortKey={view.sortKey()}
              sortOptions={view.sortOptions}
              onSortChange={view.setSort}
              dir={view.dir()}
              onToggleDir={view.toggleDir}
              count={view.count()}
              total={view.total()}
            />
          </div>
          <Suspense
            fallback={
              <div class="p-4">
                <LoadingText />
              </div>
            }
          >
            <Show when={summariesResource.error}>
              <div class="p-4">
                <ErrorState
                  message="FAILED TO LOAD REPORTS"
                  hint="Could not retrieve the research library."
                />
              </div>
            </Show>
            <Show when={!summariesResource.error}>
              <Show
                when={view.items().length > 0}
                fallback={
                  <EmptyState
                    icon="research"
                    message="NO REPORTS"
                    hint={
                      view.isFiltered()
                        ? "No reports match your search."
                        : "Run a research query to generate your first report."
                    }
                  />
                }
              >
                <For each={view.items()}>
                  {(r) => (
                    <ListRow
                      label={r.title}
                      leading="file"
                      href={`/research/${r.id}`}
                      right={
                        <div class="flex items-center gap-3">
                          <Text variant="micro" tone="dim">
                            {r.sourceCount} SRC
                          </Text>
                          <Text variant="micro" tone="dim">
                            {relativeTime(r.createdAt)}
                          </Text>
                          <StatusFlag status={statusMap[r.status]}>
                            {r.status.toUpperCase()}
                          </StatusFlag>
                          <Menu
                            trigger={
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="settings"
                              />
                            }
                            items={[
                              {
                                label: "Archive",
                                icon: "archive",
                                onSelect: () => handleArchive(r),
                              },
                              {
                                label: "Delete",
                                icon: "trash",
                                danger: true,
                                onSelect: () => handleDelete(r),
                              },
                            ]}
                          />
                        </div>
                      }
                    />
                  )}
                </For>
              </Show>
            </Show>
          </Suspense>
        </Panel>
      </Show>
    </Stack>
  );
}
