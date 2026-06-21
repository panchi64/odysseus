import { For, Show, type JSX } from "solid-js";
import {
  Button,
  Chip,
  Composer,
  ErrorState,
  InstrumentBand,
  LoadingText,
  Panel,
  ProgressBar,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import { num } from "~/lib/format";
import { createComposerAttachments } from "~/features/uploads/data";
import type { ResearchRunState, ResearchPhase } from "../model";
import { PhaseTrack } from "./PhaseTrack";

interface RunPanelProps {
  running: boolean;
  state: ResearchRunState;
  onRun: (query: string, attachmentIds: string[]) => void;
}

const statusForPhase = (phase: ResearchPhase, running: boolean) => {
  if (!running && phase !== "DONE") return "idle" as const;
  if (phase === "DONE") return "nominal" as const;
  return "info" as const;
};

const EXAMPLE_QUERIES = [
  "Compare the energy efficiency of leading local-LLM inference runtimes in 2026",
  "What are the trade-offs between RAG and long-context for personal knowledge bases?",
  "Summarize recent advances in on-device speech-to-text for Apple Silicon",
];

/** Compose panel: query input + live phase/progress display. */
export function RunPanel(props: RunPanelProps): JSX.Element {
  // Supporting files attach via the same uploads pipeline as chat; the run
  // references their ids. The Composer owns the field, draft, and attach chips.
  const attachments = createComposerAttachments();

  const hasError = () => Boolean(props.state.error);

  return (
    <Stack gap={4}>
      <Panel
        label="RESEARCH QUERY"
        state={props.running ? "active" : "default"}
        meta={
          <StatusFlag
            status={
              hasError()
                ? "alert"
                : statusForPhase(props.state.phase, props.running)
            }
            dot={props.running}
          >
            {hasError()
              ? "ERROR"
              : props.running
                ? props.state.phase
                : props.state.phase === "DONE"
                  ? "COMPLETE"
                  : "IDLE"}
          </StatusFlag>
        }
      >
        <Stack gap={3}>
          <Show when={!props.running}>
            <Stack gap={2}>
              <Text variant="micro" tone="dim">
                TRY AN EXAMPLE
              </Text>
              <div class="flex flex-wrap gap-2">
                <For each={EXAMPLE_QUERIES}>
                  {(example) => (
                    <Chip onClick={() => props.onRun(example, [])}>
                      {example}
                    </Chip>
                  )}
                </For>
              </div>
            </Stack>
          </Show>
          <Composer
            size="md"
            disabled={props.running}
            attachments={attachments}
            storageKey="research:query"
            placeholder="What do you want to research? Be specific — the engine will plan, search, read, and synthesize."
            onSend={(query, ids) => props.onRun(query, ids)}
          />
        </Stack>
      </Panel>

      {/* Error state: shown when a run fails mid-synthesis */}
      <Show when={hasError()}>
        <Panel label="SYNTHESIS FAILED" state="default">
          <ErrorState
            message={`SYNTHESIS FAILED — ${props.state.error ?? "Unknown error"}`}
            hint="The research run encountered an error. Retry the same query or modify it and try again."
            onRetry={() =>
              props.onRun(props.state.query, props.state.attachmentIds)
            }
            retryLabel="RETRY"
          />
        </Panel>
      </Show>

      {/* Progress panel: shown during run or after completion */}
      <Show
        when={(props.running || props.state.phase === "DONE") && !hasError()}
      >
        <Panel
          label="LIVE PROGRESS"
          state={props.running ? "active" : "default"}
          meta={
            <Text variant="micro" tone="dim">
              ROUND {num(props.state.round, 0)} / 4
            </Text>
          }
        >
          <Stack gap={4}>
            <PhaseTrack current={props.state.phase} />
            <ProgressBar
              value={props.state.progress}
              tone={props.state.phase === "DONE" ? "nominal" : "info"}
              showValue
            />
            <InstrumentBand
              items={[
                { label: "ROUND", value: String(props.state.round) },
                { label: "SOURCES", value: String(props.state.sourcesFound) },
                {
                  label: "FINDINGS",
                  value: String(props.state.findingsExtracted),
                },
                {
                  label: "PHASE",
                  value: props.state.phase,
                  tone: props.state.phase === "DONE" ? "nominal" : "info",
                },
              ]}
            />
            <Show when={props.running}>
              <LoadingText label={`${props.state.phase}…`} />
            </Show>
            <Show when={props.state.phase === "DONE" && !props.running}>
              <div class="flex items-center justify-between gap-3">
                <StatusFlag status="nominal">SYNTHESIS COMPLETE</StatusFlag>
                <Button
                  variant="ghost"
                  leading="arrow-right"
                  href="/research/r-007"
                >
                  VIEW REPORT
                </Button>
              </div>
            </Show>
          </Stack>
        </Panel>
      </Show>
    </Stack>
  );
}
