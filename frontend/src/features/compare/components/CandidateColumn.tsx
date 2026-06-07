import { Show, type JSX } from "solid-js";
import {
  Button,
  ErrorState,
  LoadingText,
  Panel,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import type { CompareCandidate, CompareSlot } from "../model";

interface CandidateColumnProps {
  candidate: CompareCandidate;
  revealed: boolean;
  winner?: CompareSlot;
  onVote: (slot: CompareSlot) => void;
  onRetry?: (slot: CompareSlot) => void;
  disabled: boolean;
}

/** Single model response column in the blind comparison layout. */
export function CandidateColumn(props: CandidateColumnProps): JSX.Element {
  const isWinner = () =>
    props.revealed && props.winner === props.candidate.slot;
  const isLoser = () =>
    props.revealed &&
    props.winner !== undefined &&
    props.winner !== props.candidate.slot;
  const panelState = () => {
    if (isWinner()) return "active" as const;
    if (isLoser()) return "default" as const;
    return "default" as const;
  };

  return (
    <Panel
      state={panelState()}
      class="flex-1 min-w-0"
      label={
        props.revealed
          ? props.candidate.model.toUpperCase()
          : `MODEL ${props.candidate.slot}`
      }
      meta={
        <Show
          when={props.revealed}
          fallback={
            <Show
              when={props.candidate.error}
              fallback={
                <StatusFlag
                  status={props.candidate.streaming ? "info" : "idle"}
                  dot={props.candidate.streaming}
                >
                  {props.candidate.streaming ? "STREAMING" : "READY"}
                </StatusFlag>
              }
            >
              <StatusFlag status="alert">ERROR</StatusFlag>
            </Show>
          }
        >
          <StatusFlag status={isWinner() ? "nominal" : "idle"}>
            {isWinner() ? "WINNER" : "—"}
          </StatusFlag>
        </Show>
      }
    >
      <Stack gap={4}>
        <div class="min-h-32">
          <Show
            when={!props.candidate.error}
            fallback={
              <ErrorState
                message={props.candidate.error}
                hint="Model timed out or returned an error."
                onRetry={
                  props.onRetry
                    ? () => props.onRetry!(props.candidate.slot)
                    : undefined
                }
                retryLabel="RETRY"
              />
            }
          >
            <Show
              when={props.candidate.response}
              fallback={
                <Show when={props.candidate.streaming}>
                  <LoadingText label="GENERATING…" />
                </Show>
              }
            >
              <Text variant="body" tone={isLoser() ? "dim" : "default"}>
                {props.candidate.response}
                <Show when={props.candidate.streaming}>
                  <span class="animate-pulse text-info">▌</span>
                </Show>
              </Text>
            </Show>
          </Show>
        </div>

        <Show when={!props.revealed}>
          <Button
            variant={props.disabled ? "ghost" : "default"}
            leading="check"
            disabled={props.disabled}
            block
            onClick={() => props.onVote(props.candidate.slot)}
          >
            VOTE MODEL {props.candidate.slot}
          </Button>
        </Show>
      </Stack>
    </Panel>
  );
}
