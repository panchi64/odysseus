import { Show, type JSX } from "solid-js";
import {
  Button,
  InstrumentBand,
  LoadingText,
  Panel,
  ProgressBar,
  Stack,
  StatusFlag,
  Text,
  Textarea,
} from "~/ui";
import { num } from "~/lib/format";
import { createSignal } from "solid-js";
import type { ResearchRunState, ResearchPhase } from "../model";
import { PhaseTrack } from "./PhaseTrack";

interface RunPanelProps {
  running: boolean;
  state: ResearchRunState;
  onRun: (query: string) => void;
}

const statusForPhase = (phase: ResearchPhase, running: boolean) => {
  if (!running && phase !== "DONE") return "idle" as const;
  if (phase === "DONE") return "nominal" as const;
  return "info" as const;
};

/** Compose panel: query input + live phase/progress display. */
export function RunPanel(props: RunPanelProps): JSX.Element {
  const [query, setQuery] = createSignal("");

  const submit = () => {
    const q = query().trim();
    if (!q || props.running) return;
    props.onRun(q);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Stack gap={4}>
      <Panel
        label="RESEARCH QUERY"
        state={props.running ? "active" : "default"}
        meta={
          <StatusFlag
            status={statusForPhase(props.state.phase, props.running)}
            dot={props.running}
          >
            {props.running
              ? props.state.phase
              : props.state.phase === "DONE"
                ? "COMPLETE"
                : "IDLE"}
          </StatusFlag>
        }
      >
        <Stack gap={3}>
          <Textarea
            rows={3}
            placeholder="What do you want to research? Be specific — the engine will plan, search, read, and synthesize."
            value={query()}
            onInput={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={onKeyDown}
            disabled={props.running}
            hint="Ctrl+Enter to run"
          />
          <div class="flex items-center justify-between gap-3">
            <Text variant="micro" tone="dim">
              Ctrl+Enter to run · multi-round deep synthesis
            </Text>
            <Button
              variant="primary"
              leading="research"
              disabled={props.running || !query().trim()}
              onClick={submit}
            >
              {props.running ? "RUNNING…" : "RUN RESEARCH"}
            </Button>
          </div>
        </Stack>
      </Panel>

      <Show when={props.running || props.state.phase === "DONE"}>
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
