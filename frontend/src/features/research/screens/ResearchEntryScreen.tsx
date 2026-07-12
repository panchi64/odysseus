import {
  Show,
  createEffect,
  createSignal,
  onCleanup,
  type JSX,
} from "solid-js";
import { createStore, reconcile } from "solid-js/store";
import { useNavigate, useParams } from "@solidjs/router";
import {
  Button,
  EmptyState,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
  type Status,
} from "~/ui";
import { openConversation } from "~/features/chat/data";
import {
  continueResearch,
  createResearchProgress,
  refineResearch,
  refreshResearchEntry,
  startResearch,
  useResearchEntry,
} from "../data";
import type { ResearchOut, ResearchStatus } from "../model";
import { ClarifyForm } from "../components/ClarifyForm";
import { PlanPanel } from "../components/PlanPanel";
import { ProgressPanel } from "../components/ProgressPanel";
import { ReportView } from "../components/ReportView";

const STATUS_MAP: Record<ResearchStatus, { status: Status; label: string }> = {
  draft: { status: "idle", label: "DRAFT" },
  running: { status: "info", label: "RUNNING" },
  done: { status: "nominal", label: "DONE" },
  error: { status: "alert", label: "ERROR" },
  cancelled: { status: "idle", label: "CANCELLED" },
};

/** One research entry across its whole lifecycle: clarify → plan/refine loop →
 *  live progress → finished report (or error/cancelled). One screen because
 *  it's one backend-persisted entry — the operator can leave and come back at
 *  any stage and see exactly where it stands (draft survives navigation; a
 *  running entry reattaches; a finished one just shows the report). */
export function ResearchEntryScreen(): JSX.Element {
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const entryResource = useResearchEntry(() => params.id);

  const [entry, setEntry] = createStore<{ value: ResearchOut | null }>({
    value: null,
  });
  createEffect(() => {
    const r = entryResource();
    if (r) setEntry("value", reconcile(r));
  });

  const [submittingAnswers, setSubmittingAnswers] = createSignal(false);
  const [skipping, setSkipping] = createSignal(false);
  const [refining, setRefining] = createSignal(false);
  const [starting, setStarting] = createSignal(false);
  const [continuing, setContinuing] = createSignal(false);

  const progress = createResearchProgress();
  let trackedRunId: string | null = null;

  // Follow a running entry's run — covers both a cold reattach (loaded straight
  // into "running") and the local transition just after START, uniformly: both
  // land here via the same store write, replaying from seq 0 either way (the
  // full history rebuilds phase/round/counts, mirroring chat's cold-reload path).
  createEffect(() => {
    const e = entry.value;
    if (e?.status === "running" && e.runId && trackedRunId !== e.runId) {
      trackedRunId = e.runId;
      void progress.start(e.runId, 0);
    }
  });

  progress.onTerminal(() => {
    refreshResearchEntry();
  });

  onCleanup(() => progress.stop());

  async function handleSubmitAnswers(answers: string[]): Promise<void> {
    if (!entry.value) return;
    setSubmittingAnswers(true);
    try {
      const out = await refineResearch(entry.value.id, { answers });
      setEntry("value", reconcile(out));
    } catch {
      toast.error("Could not submit your answers — try again.");
    } finally {
      setSubmittingAnswers(false);
    }
  }

  /** The clarify step's skip/start-now affordance (DR-1.6): forces `refine`
   *  straight to a plan (neither `answers` nor `feedback`), so the operator
   *  always has a reachable path to START RESEARCH without answering. */
  async function handleSkipClarify(): Promise<void> {
    if (!entry.value) return;
    setSkipping(true);
    try {
      const out = await refineResearch(entry.value.id, {});
      setEntry("value", reconcile(out));
    } catch {
      toast.error("Could not skip ahead — try again.");
    } finally {
      setSkipping(false);
    }
  }

  async function handleRefine(feedback: string): Promise<void> {
    if (!entry.value || !feedback.trim()) return;
    setRefining(true);
    try {
      const out = await refineResearch(entry.value.id, { feedback });
      setEntry("value", reconcile(out));
    } catch {
      toast.error("Could not refine the plan — try again.");
    } finally {
      setRefining(false);
    }
  }

  async function handleStart(): Promise<void> {
    if (!entry.value) return;
    setStarting(true);
    try {
      const out = await startResearch(entry.value.id);
      setEntry("value", reconcile(out));
    } catch {
      toast.error("Could not start the run — try again.");
    } finally {
      setStarting(false);
    }
  }

  async function handleContinueInChat(): Promise<void> {
    if (!entry.value) return;
    setContinuing(true);
    try {
      const { conversationId } = await continueResearch(entry.value.id);
      openConversation(conversationId);
      navigate("/chat");
    } catch {
      toast.error("Could not start the follow-up conversation.");
    } finally {
      setContinuing(false);
    }
  }

  return (
    <Show
      when={entry.value}
      fallback={
        <Show
          when={entryResource.error}
          fallback={
            <div class="p-6">
              <LoadingText label="LOADING…" />
            </div>
          }
        >
          <EmptyState
            icon="research"
            message="RESEARCH ENTRY NOT FOUND"
            hint="It may have been deleted."
            action={
              <Button variant="default" leading="chevron-left" href="/research">
                BACK TO LIBRARY
              </Button>
            }
          />
        </Show>
      }
    >
      {(e) => {
        const meta = () => STATUS_MAP[e().status];
        return (
          <Stack gap={6}>
            <Button
              variant="ghost"
              leading="chevron-left"
              href="/research"
              class="self-start"
            >
              BACK TO LIBRARY
            </Button>

            <PageHeader
              title={e().question}
              assetId={`RES-${e().id.toUpperCase()}`}
              actions={
                <StatusFlag
                  status={meta().status}
                  dot={e().status === "running"}
                >
                  {meta().label}
                </StatusFlag>
              }
            />

            <Show when={e().status === "draft"}>
              <Show
                when={e().plan}
                fallback={
                  <ClarifyForm
                    questions={e().clarifyingQuestions ?? []}
                    submitting={submittingAnswers()}
                    skipping={skipping()}
                    onSubmit={handleSubmitAnswers}
                    onSkip={handleSkipClarify}
                  />
                }
              >
                {(plan) => (
                  <PlanPanel
                    plan={plan()}
                    refining={refining()}
                    starting={starting()}
                    onRefine={handleRefine}
                    onStart={handleStart}
                  />
                )}
              </Show>
            </Show>

            <Show when={e().status === "running"}>
              <ProgressPanel
                state={progress.state}
                onCancel={() => void progress.cancel()}
                onReattach={progress.reattach}
              />
            </Show>

            <Show when={e().status === "done"}>
              <ReportView
                entry={e()}
                continuing={continuing()}
                onContinueInChat={handleContinueInChat}
              />
            </Show>

            <Show when={e().status === "error"}>
              <Panel state="alert">
                <Stack gap={1}>
                  <StatusFlag status="alert">RESEARCH FAILED</StatusFlag>
                  <Text variant="body" tone="dim">
                    {e().report ??
                      progress.state.errorMessage ??
                      "This research run failed. Check the notification center for details."}
                  </Text>
                </Stack>
              </Panel>
            </Show>

            <Show when={e().status === "cancelled"}>
              <Panel>
                <Row gap={3} align="center">
                  <StatusFlag status="idle">CANCELLED</StatusFlag>
                  <Text variant="body" tone="dim">
                    This research run was cancelled before it finished.
                  </Text>
                </Row>
              </Panel>
            </Show>
          </Stack>
        );
      }}
    </Show>
  );
}
