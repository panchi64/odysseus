import { For, Show, createSignal, type JSX } from "solid-js";
import { Button, Divider, Panel, Row, Stack, Text, Textarea } from "~/ui";
import type { ResearchPlan } from "../model";

interface PlanPanelProps {
  plan: ResearchPlan;
  /** A refine request is in flight. */
  refining: boolean;
  /** A start request is in flight. */
  starting: boolean;
  onRefine: (feedback: string) => void;
  /** Always visible/enabled once a plan exists — the skip/start-now
   *  affordance DR-1.6 requires at every step of the refinement loop. */
  onStart: () => void;
}

/** The plan-preview + iterative-refinement step of the pre-run flow: objective,
 *  angles, and optional planner notes, with a free-text feedback box that loops
 *  back through `refine` any number of times, and an always-present START. */
export function PlanPanel(props: PlanPanelProps): JSX.Element {
  const [feedback, setFeedback] = createSignal("");
  const busy = () => props.refining || props.starting;

  return (
    <Panel
      label="RESEARCH PLAN"
      meta={
        <Text variant="micro" tone="dim">
          {props.plan.angles.length} ANGLES
        </Text>
      }
    >
      <Stack gap={4}>
        <Stack gap={1}>
          <Text variant="label" tone="dim">
            OBJECTIVE
          </Text>
          <Text variant="body">{props.plan.objective}</Text>
        </Stack>

        <Stack gap={1}>
          <Text variant="label" tone="dim">
            ANGLES
          </Text>
          <ul class="flex flex-col gap-1 list-disc pl-5">
            <For each={props.plan.angles}>
              {(angle) => (
                <li>
                  <Text variant="body">{angle}</Text>
                </li>
              )}
            </For>
          </ul>
        </Stack>

        <Show when={props.plan.notes}>
          <Stack gap={1}>
            <Text variant="label" tone="dim">
              NOTES
            </Text>
            <Text variant="body" tone="dim">
              {props.plan.notes}
            </Text>
          </Stack>
        </Show>

        <Divider />

        <Stack gap={2}>
          <Text variant="label" tone="dim">
            REFINE WITH FEEDBACK (OPTIONAL)
          </Text>
          <Textarea
            rows={3}
            value={feedback()}
            onInput={(e) => setFeedback(e.currentTarget.value)}
            placeholder="e.g. focus more on X, drop Y, add a cost comparison…"
            disabled={busy()}
          />
          <Row justify="between" align="center" gap={2}>
            <Button
              variant="default"
              disabled={!feedback().trim() || busy()}
              onClick={() => {
                const text = feedback().trim();
                setFeedback("");
                props.onRefine(text);
              }}
            >
              REFINE PLAN
            </Button>
            <Button
              variant="primary"
              leading="send"
              disabled={busy()}
              onClick={props.onStart}
            >
              START RESEARCH
            </Button>
          </Row>
        </Stack>
      </Stack>
    </Panel>
  );
}
