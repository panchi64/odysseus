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
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useReport } from "../data";

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
          />
        }
      >
        {(r) => (
          <Stack gap={6}>
            <PageHeader
              title={r().title}
              subtitle={r().query}
              assetId={`RES-${r().id.toUpperCase()}`}
              actions={
                <div class="flex items-center gap-2">
                  <StatusFlag status="nominal">COMPLETE</StatusFlag>
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

            {/* Follow-up action */}
            <Panel>
              <Row gap={3} align="center" justify="between">
                <Stack gap={1}>
                  <Text variant="label" tone="bright">
                    START FOLLOW-UP CONVERSATION
                  </Text>
                  <Text variant="micro" tone="dim">
                    Continue this research in a new chat session with the report
                    loaded as context.
                  </Text>
                </Stack>
                <Button variant="primary" leading="send" href="/chat">
                  OPEN CHAT
                </Button>
              </Row>
            </Panel>
          </Stack>
        )}
      </Show>
    </Suspense>
  );
}
