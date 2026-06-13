import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  LoadingText,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
} from "~/ui";
import { pct } from "~/lib/format";
import { useLeaderboard, createCompareRun } from "../compare/data";
import { CandidateColumn } from "../compare/CandidateColumn";
import type { CompareSlot } from "../compare/model";

/** Blind model comparison — the COMPARE tab of the Model Cookbook. Submit a
 *  prompt, watch both models respond anonymously, vote, then reveal identities.
 *  Owns no page chrome; the Cookbook screen provides the header. */
export function ComparePanel(): JSX.Element {
  const [prompt, setPrompt] = createSignal("");
  const leaderboard = useLeaderboard();
  const { run, active, start, vote, stop, reset } = createCompareRun();

  const bothDone = () =>
    run.candidates.length === 2 && run.candidates.every((c) => !c.streaming);

  const voteDisabledReason = () => {
    if (run.revealed) return "You've already voted on this comparison.";
    if (active() || !bothDone())
      return "Wait for both responses to finish streaming before voting.";
    return undefined;
  };

  const handleStart = () => {
    const p = prompt().trim();
    if (!p) return;
    start(p);
  };

  const handleVote = (slot: CompareSlot) => {
    if (!bothDone()) return;
    vote(slot as "A" | "B");
    toast.success("VOTE RECORDED");
  };

  const handleStop = () => {
    stop();
    toast.info("COMPARISON STOPPED");
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleStart();
    }
  };

  return (
    <Stack gap={6}>
      {/* Prompt input */}
      <Panel
        label="PROMPT"
        state={active() ? "active" : "default"}
        meta={
          <Row gap={2} align="center">
            <StatusFlag status={active() ? "info" : "idle"} dot={active()}>
              {active() ? "STREAMING" : run.id ? "AWAITING VOTE" : "IDLE"}
            </StatusFlag>
            <Show when={run.id}>
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                onClick={reset}
              >
                RESET
              </Button>
            </Show>
          </Row>
        }
      >
        <Stack gap={3}>
          <Textarea
            rows={3}
            placeholder="Enter a prompt to compare model responses side-by-side. Good prompts have a definitive better answer."
            value={prompt()}
            onInput={(e) => setPrompt(e.currentTarget.value)}
            onKeyDown={onKeyDown}
            disabled={active() || (run.id !== "" && !run.revealed)}
            hint="Ctrl+Enter to compare"
          />
          <div class="flex items-center justify-between gap-3">
            <Text variant="micro" tone="dim">
              Ctrl+Enter · responses are anonymized until you vote
            </Text>
            <Row gap={2}>
              <Show when={active()}>
                <Button variant="default" leading="stop" onClick={handleStop}>
                  STOP
                </Button>
              </Show>
              <Button
                variant="primary"
                leading="compare"
                disabled={
                  active() ||
                  !prompt().trim() ||
                  (run.id !== "" && !run.revealed)
                }
                onClick={handleStart}
              >
                COMPARE
              </Button>
            </Row>
          </div>
        </Stack>
      </Panel>

      {/* Comparison columns */}
      <Show when={run.candidates.length > 0}>
        <Stack gap={3}>
          <Show when={run.revealed}>
            <InstrumentBand
              items={[
                {
                  label: "WINNER",
                  value:
                    run.candidates
                      .find((c) => c.slot === run.winner)
                      ?.model.toUpperCase() ?? "—",
                  tone: "nominal",
                },
                { label: "ROUND", value: run.id },
              ]}
            />
          </Show>

          <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <For each={run.candidates}>
              {(candidate) => (
                <CandidateColumn
                  candidate={candidate}
                  revealed={run.revealed}
                  winner={run.winner}
                  onVote={handleVote}
                  disabled={active() || run.revealed || !bothDone()}
                  disabledReason={voteDisabledReason()}
                />
              )}
            </For>
          </div>

          <Show when={!run.revealed && bothDone()}>
            <Panel>
              <Row gap={2} align="center" justify="center">
                <Text variant="micro" tone="dim">
                  Both responses ready — vote for the better answer to reveal
                  model identities.
                </Text>
              </Row>
            </Panel>
          </Show>

          <Show when={run.revealed}>
            <Panel>
              <Row gap={3} align="center" justify="between">
                <Stack gap={1}>
                  <Text variant="label" tone="bright">
                    RUN ANOTHER COMPARISON
                  </Text>
                  <Text variant="micro" tone="dim">
                    Vote recorded. Enter a new prompt to compare again.
                  </Text>
                </Stack>
                <Button
                  variant="default"
                  leading="refresh"
                  onClick={() => {
                    reset();
                    setPrompt("");
                  }}
                >
                  NEW COMPARISON
                </Button>
              </Row>
            </Panel>
          </Show>
        </Stack>
      </Show>

      {/* Leaderboard */}
      <Panel
        label="LEADERBOARD"
        meta={
          <Text variant="micro" tone="dim">
            <Suspense fallback="…">
              {leaderboard()?.length ?? 0} MODELS
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
            when={(leaderboard()?.length ?? 0) > 0}
            fallback={
              <EmptyState
                icon="compare"
                message="NO VOTES YET"
                hint="Run a comparison and vote to populate the leaderboard."
              />
            }
          >
            <For each={leaderboard()}>
              {(entry, i) => (
                <div class="flex items-center gap-3 px-4 py-3 border-b border-line last:border-b-0">
                  <Text
                    variant="label"
                    tone="dim"
                    class="w-6 shrink-0 tabular-nums"
                  >
                    {(i() + 1).toString().padStart(2, "0")}
                  </Text>
                  <Text
                    variant="body"
                    tone="bright"
                    class="flex-1 min-w-0 truncate"
                  >
                    {entry.model}
                  </Text>
                  <div class="flex items-center gap-4 shrink-0">
                    <div class="w-24">
                      <ProgressBar
                        value={entry.winRate * 100}
                        tone={
                          entry.winRate >= 0.7
                            ? "nominal"
                            : entry.winRate >= 0.4
                              ? "warn"
                              : "alert"
                        }
                      />
                    </div>
                    <Text
                      variant="readout"
                      tone="bright"
                      class="w-12 text-right tabular-nums"
                    >
                      {pct(entry.winRate * 100)}
                    </Text>
                    <Text
                      variant="micro"
                      tone="dim"
                      class="w-20 text-right tabular-nums"
                    >
                      {entry.wins}W {entry.losses}L
                    </Text>
                  </div>
                </div>
              )}
            </For>
          </Show>
        </Suspense>
      </Panel>
    </Stack>
  );
}
