import { For, Show, Suspense, type JSX } from "solid-js";
import { useParams } from "@solidjs/router";
import {
  Button,
  Divider,
  EmptyState,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  type Status,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useReport } from "../data";
import type { ResearchStatus } from "../model";

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}S`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}M ${rem}S` : `${m}M`;
}

function relevancePct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

const statusMap: Record<ResearchStatus, { status: Status; label: string }> = {
  complete: { status: "nominal", label: "COMPLETE" },
  archived: { status: "idle", label: "ARCHIVED" },
  error: { status: "alert", label: "ERROR" },
  running: { status: "info", label: "RUNNING" },
};

/** Full synthesized report view with metadata, sections, and cited sources. */
export function ResearchReportScreen(): JSX.Element {
  const params = useParams<{ id: string }>();
  const report = useReport(() => params.id);

  return (
    <Suspense
      fallback={
        <div class="p-6">
          <LoadingText label="LOADING REPORT…" />
        </div>
      }
    >
      <Show
        when={report()}
        fallback={
          <EmptyState
            icon="file"
            message="REPORT NOT FOUND"
            hint="The requested research report does not exist."
            action={
              <Button variant="default" leading="chevron-left" href="/research">
                BACK TO LIBRARY
              </Button>
            }
          />
        }
      >
        {(r) => (
          <Stack gap={6}>
            {/* Persistent return path to the library, regardless of status. */}
            <Button
              variant="ghost"
              leading="chevron-left"
              href="/research"
              class="self-start"
            >
              BACK TO LIBRARY
            </Button>

            {/* Error state: report failed mid-synthesis */}
            <Show when={r().status === "error"}>
              <Panel state="alert">
                <Stack gap={1}>
                  <StatusFlag status="alert">SYNTHESIS FAILED</StatusFlag>
                  <Text variant="body" tone="dim">
                    This report encountered an error during synthesis. Some
                    sections or sources may be missing or incomplete.
                  </Text>
                </Stack>
              </Panel>
            </Show>

            {/* Archived banner */}
            <Show when={r().status === "archived"}>
              <Panel>
                <Row gap={3} align="center">
                  <StatusFlag status="idle">ARCHIVED</StatusFlag>
                  <Text variant="body" tone="dim">
                    This report is no longer active. It may contain outdated
                    information.
                  </Text>
                </Row>
              </Panel>
            </Show>

            <PageHeader
              title={r().title}
              subtitle={r().query}
              assetId={`RES-${r().id.toUpperCase()}`}
              actions={
                <div class="flex items-center gap-2">
                  <StatusFlag status={statusMap[r().status].status}>
                    {statusMap[r().status].label}
                  </StatusFlag>
                  <Button variant="ghost" leading="send" href="/chat">
                    FOLLOW-UP
                  </Button>
                </div>
              }
            />

            <InstrumentBand
              items={[
                { label: "ROUNDS", value: String(r().rounds) },
                { label: "SOURCES", value: String(r().sourceCount) },
                { label: "FINDINGS", value: String(r().findingCount) },
                { label: "DURATION", value: formatDuration(r().durationMs) },
                { label: "CREATED", value: relativeTime(r().createdAt) },
              ]}
            />

            {/* Report body */}
            <Panel label="SYNTHESIS">
              <Stack gap={6}>
                <For each={r().sections}>
                  {(section, i) => (
                    <>
                      <Stack gap={2}>
                        <Text variant="label" tone="bright">
                          {section.heading}
                        </Text>
                        <Text variant="body" tone="default">
                          {section.body}
                        </Text>
                      </Stack>
                      <Show when={i() < r().sections.length - 1}>
                        <Divider />
                      </Show>
                    </>
                  )}
                </For>
              </Stack>
            </Panel>

            {/* Cited sources */}
            <Panel
              label="CITED SOURCES"
              meta={
                <Text variant="micro" tone="dim">
                  {r().sourceCount} SOURCES
                </Text>
              }
              flush
            >
              <For each={r().sources}>
                {(source) => (
                  <ListRow
                    label={source.title}
                    leading="link"
                    href={source.url}
                    right={
                      <div class="flex items-center gap-4">
                        <Text variant="micro" tone="dim">
                          {source.domain}
                        </Text>
                        <div class="w-16">
                          <Row gap={1} align="center" justify="end">
                            <Text
                              variant="micro"
                              tone={
                                source.relevance >= 0.9
                                  ? "nominal"
                                  : source.relevance >= 0.7
                                    ? "default"
                                    : "dim"
                              }
                            >
                              {relevancePct(source.relevance)}
                            </Text>
                          </Row>
                        </div>
                      </div>
                    }
                  />
                )}
              </For>
            </Panel>

            {/* Follow-up action — only show for complete reports */}
            <Show when={r().status === "complete"}>
              <Panel>
                <Row gap={3} align="center" justify="between">
                  <Stack gap={1}>
                    <Text variant="label" tone="bright">
                      START FOLLOW-UP CONVERSATION
                    </Text>
                    <Text variant="micro" tone="dim">
                      Continue this research in a new chat session with the
                      report loaded as context.
                    </Text>
                  </Stack>
                  <Button variant="primary" leading="send" href="/chat">
                    OPEN CHAT
                  </Button>
                </Row>
              </Panel>
            </Show>
          </Stack>
        )}
      </Show>
    </Suspense>
  );
}
