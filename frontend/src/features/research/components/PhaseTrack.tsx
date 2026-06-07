import { For, type JSX } from "solid-js";
import { Text } from "~/ui";
import { cx } from "~/ui";
import type { ResearchPhase } from "../model";

const PHASES: ResearchPhase[] = [
  "PLANNING",
  "SEARCHING",
  "READING",
  "ANALYZING",
  "WRITING",
];

interface PhaseTrackProps {
  current: ResearchPhase;
}

function phaseOrdinal(phase: ResearchPhase): number {
  return PHASES.indexOf(phase);
}

/** Horizontal phase progress indicator for the live-run panel. */
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
                  "h-0.5 w-full transition-colors",
                  done() ? "bg-nominal" : active() ? "bg-info" : "bg-line",
                )}
              />
              <Text
                variant="micro"
                tone={done() ? "nominal" : active() ? "info" : "dim"}
                class="truncate px-1"
              >
                {phase}
              </Text>
            </div>
          );
        }}
      </For>
    </div>
  );
}
