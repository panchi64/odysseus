import { Show, type JSX } from "solid-js";
import {
  Button,
  InstrumentBand,
  LoadingText,
  Panel,
  Row,
  Stack,
  Text,
} from "~/ui";
import type { ResearchProgressState } from "../model";
import { PhaseTrack } from "./PhaseTrack";

interface ProgressPanelProps {
  state: ResearchProgressState;
  onCancel: () => void;
  onReattach: () => void;
}

/** Live progress for a running research entry: the current phase, round
 *  counter, and cumulative sources/findings — exactly what the pipeline
 *  documents it streams (DR-5.1) — plus cancel and a reattach affordance for
 *  a dropped transport (mirrors chat's detached state). */
export function ProgressPanel(props: ProgressPanelProps): JSX.Element {
  const phaseLabel = () => props.state.phase?.toUpperCase() ?? "STARTING…";

  return (
    <Panel
      label="LIVE PROGRESS"
      state="active"
      meta={
        <Text variant="micro" tone="dim">
          ROUND {Math.max(props.state.round, 1)}
        </Text>
      }
    >
      <Stack gap={4}>
        <PhaseTrack current={props.state.phase} />
        <InstrumentBand
          items={[
            { label: "ROUND", value: String(Math.max(props.state.round, 1)) },
            { label: "SOURCES", value: String(props.state.sources) },
            { label: "FINDINGS", value: String(props.state.findings) },
            { label: "PHASE", value: phaseLabel(), tone: "info" },
          ]}
        />

        <Show when={props.state.detached}>
          <Row
            justify="between"
            align="center"
            gap={2}
            class="border border-warn/40 px-3 py-2"
          >
            <Text variant="micro" tone="warn">
              Connection lost — the run may still be active.
            </Text>
            <Button
              variant="default"
              leading="refresh"
              onClick={props.onReattach}
            >
              RECONNECT
            </Button>
          </Row>
        </Show>

        <Row justify="between" align="center" gap={2}>
          <LoadingText label={phaseLabel()} />
          <Button variant="danger" leading="stop" onClick={props.onCancel}>
            CANCEL
          </Button>
        </Row>
      </Stack>
    </Panel>
  );
}
