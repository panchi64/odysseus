import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  ListRow,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  type Status,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useReportSummaries, createResearchRun } from "../data";
import { RunPanel } from "../components/RunPanel";
import type { ResearchStatus } from "../model";

const statusMap: Record<ResearchStatus, Status> = {
  complete: "nominal",
  running: "info",
  archived: "idle",
  error: "alert",
};

/** Research library + run hub. Two-tab layout: RUN and LIBRARY. */
export function ResearchLibraryScreen(): JSX.Element {
  const [tab, setTab] = createSignal<string>("run");
  const summaries = useReportSummaries();
  const { running, state, run } = createResearchRun();

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
        <Panel
          label="RESEARCH REPORTS"
          meta={
            <Text variant="micro" tone="dim">
              <Suspense fallback="…">
                {summaries()?.length ?? 0} REPORTS
              </Suspense>
            </Text>
          }
          flush
        >
          <Suspense
            fallback={
              <div class="p-4">
                <LoadingText />
              </div>
            }
          >
            <Show
              when={(summaries()?.length ?? 0) > 0}
              fallback={
                <EmptyState
                  icon="research"
                  message="NO REPORTS"
                  hint="Run a research query to generate your first report."
                />
              }
            >
              <For each={summaries()}>
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
                              label: "View Report",
                              icon: "arrow-right",
                              onSelect: () => {},
                            },
                            {
                              label: "Archive",
                              icon: "archive",
                              onSelect: () => {},
                            },
                            {
                              label: "Delete",
                              icon: "trash",
                              danger: true,
                              onSelect: () => {},
                            },
                          ]}
                        />
                      </div>
                    }
                  />
                )}
              </For>
            </Show>
          </Suspense>
        </Panel>
      </Show>
    </Stack>
  );
}
