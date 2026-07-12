import { For, type JSX } from "solid-js";
import { Text, cx } from "~/ui";
import type { ResearchPhase } from "../model";

const PHASES: ResearchPhase[] = [
  "planning",
  "searching",
  "reading",
  "analyzing",
  "writing",
];

interface PhaseTrackProps {
  /** Null before the first `step.started` frame has arrived. */
  current: ResearchPhase | null;
}

function phaseOrdinal(phase: ResearchPhase | null): number {
  return phase === null ? -1 : PHASES.indexOf(phase);
}

/** Horizontal phase progress indicator for the live-run panel — the five
 *  phases DR-5.1 requires the stream to convey, in pipeline order. */
export function PhaseTrack(props: PhaseTrackProps): JSX.Element {
  return (
    <div class="flex items-stretch gap-0 w-full">
      <For each={PHASES}>
        {(phase, i) => {
          const currentOrd = () => phaseOrdinal(props.current);
          const thisOrd = i();
          const done = () => thisOrd < currentOrd();
          const active = () => thisOrd === currentOrd();
          return (
            <div class="flex flex-1 flex-col gap-1 min-w-0">
              <div
                class={cx(
                  "h-0.5 w-full transition-colors transition-fast",
                  done() ? "bg-nominal" : active() ? "bg-info" : "bg-line",
                )}
              />
              <Text
                variant="micro"
                tone={done() ? "nominal" : active() ? "info" : "dim"}
                class="truncate px-1"
              >
                {phase.toUpperCase()}
              </Text>
            </div>
          );
        }}
      </For>
    </div>
  );
}
