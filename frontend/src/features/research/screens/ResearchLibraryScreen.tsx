import { For, Show, createSignal, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  Chip,
  Composer,
  ListRow,
  ListToolbar,
  Menu,
  PageHeader,
  Panel,
  Resource,
  Stack,
  StatusFlag,
  Text,
  confirm,
  toast,
  type Status,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import { deleteResearch, intakeResearch, useResearchList } from "../data";
import type { ResearchListItem, ResearchStatus } from "../model";

const STATUS_MAP: Record<ResearchStatus, { status: Status; label: string }> = {
  draft: { status: "idle", label: "Draft" },
  running: { status: "info", label: "Running" },
  done: { status: "nominal", label: "Done" },
  error: { status: "alert", label: "Error" },
  cancelled: { status: "idle", label: "Cancelled" },
};

const EXAMPLE_QUERIES = [
  "Compare the energy efficiency of leading local-LLM inference runtimes in 2026",
  "What are the trade-offs between RAG and long-context for personal knowledge bases?",
  "Summarize recent advances in on-device speech-to-text for Apple Silicon",
];

/** Research library + new-research entry point. A question starts a draft
 *  (`intake`) and hands off to the entry screen for clarify/plan/refine/start —
 *  this screen never drives that flow itself. */
export function ResearchLibraryScreen(): JSX.Element {
  const navigate = useNavigate();
  const list = useResearchList();
  const [starting, setStarting] = createSignal(false);

  const view = createListView({
    source: () => list() ?? [],
    search: (r: ResearchListItem) => r.question,
    sorts: {
      recent: {
        label: "Date",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
      status: {
        label: "Status",
        compare: (a, b) => a.status.localeCompare(b.status),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
  });

  async function handleStart(question: string): Promise<void> {
    const q = question.trim();
    if (!q || starting()) return;
    setStarting(true);
    try {
      const out = await intakeResearch(q);
      navigate(`/research/${out.id}`);
    } catch {
      toast.error("Could not start research — try again.");
    } finally {
      setStarting(false);
    }
  }

  async function handleDelete(r: ResearchListItem): Promise<void> {
    const ok = await confirm({
      title: `Delete "${r.question}"?`,
      detail:
        "This research entry and its report (if any) will be permanently removed. This cannot be undone.",
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteResearch(r.id);
      toast.success("Deleted.");
    } catch {
      toast.error("Could not delete this entry.");
    }
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="Deep research"
        subtitle="Multi-round synthesis engine. Plan → search → read → analyze → write."
        assetId="ODY-RES-01.0"
      />

      {/* Bare: the composer inside carries the bloom, so a grey card around it
          would be a second surface competing with the one that matters. */}
      <Panel
        label="New research"
        bare
        state={starting() ? "active" : "default"}
      >
        <Stack gap={3}>
          <Stack gap={2}>
            <Text variant="micro" tone="dim">
              Try an example
            </Text>
            <div class="flex flex-wrap gap-2">
              <For each={EXAMPLE_QUERIES}>
                {(example) => (
                  <Chip onClick={() => handleStart(example)}>{example}</Chip>
                )}
              </For>
            </div>
          </Stack>
          <Composer
            size="md"
            bare
            disabled={starting()}
            storageKey="research:query"
            placeholder="What do you want to research? Be specific — the engine will plan, search, read, and synthesize."
            onSend={(question) => handleStart(question)}
          />
        </Stack>
      </Panel>

      <Panel label="Library" flush>
        <div class="p-3">
          <ListToolbar
            query={view.query()}
            onQueryChange={view.setQuery}
            placeholder="Search by question…"
            sortKey={view.sortKey()}
            sortOptions={view.sortOptions}
            onSortChange={view.setSort}
            dir={view.dir()}
            onToggleDir={view.toggleDir}
            count={view.count()}
            total={view.total()}
          />
        </div>
        <Resource
          data={list}
          emptyMessage="No research yet"
          emptyHint="Ask a question above to generate your first report."
          isEmpty={(items) => items.length === 0}
        >
          {() => (
            <Show
              when={view.items().length > 0}
              fallback={
                <div class="p-4">
                  <Text variant="body" tone="dim">
                    No entries match your search.
                  </Text>
                </div>
              }
            >
              <For each={view.items()}>
                {(r) => {
                  const meta = STATUS_MAP[r.status];
                  return (
                    <ListRow
                      label={r.question}
                      leading="file"
                      href={`/research/${r.id}`}
                      right={
                        <>
                          <Show when={r.stats}>
                            {(s) => (
                              <Text variant="micro" tone="dim">
                                {s().sources} SRC
                              </Text>
                            )}
                          </Show>
                          <Text variant="micro" tone="dim">
                            {relativeTime(r.createdAt)}
                          </Text>
                          <StatusFlag
                            status={meta.status}
                            dot={r.status === "running"}
                          >
                            {meta.label}
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
                                label: "Delete",
                                icon: "trash",
                                danger: true,
                                onSelect: () => handleDelete(r),
                              },
                            ]}
                          />
                        </>
                      }
                    />
                  );
                }}
              </For>
            </Show>
          )}
        </Resource>
      </Panel>
    </Stack>
  );
}
