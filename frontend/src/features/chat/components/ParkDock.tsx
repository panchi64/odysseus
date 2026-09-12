import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { Button, ConstructionReveal, Row, Stack, Text } from "~/ui";
import type { Park } from "../stream/approvals";
import type { ApprovalDecision, QuestionAnswer, QuestionReply } from "../model";
import { ApprovalPanel } from "./ApprovalPanel";
import { QuestionPanel } from "./QuestionPanel";

/**
 * **Where a parked run asks.** The composer's own slot, taken over by a frosted panel
 * for exactly as long as the run is waiting on the operator.
 *
 * It replaces the composer rather than floating above it, and that is the whole design.
 * A parked run cannot act on a message; leaving the input there offers the operator a
 * gesture that would be silently swallowed, next to the one that would actually move
 * things on. Docked, the question also cannot scroll out of reach the way an inline card
 * could — the operator's attention and the run's next step are in the same place.
 *
 * **Everything the park holds submits together**, whichever kinds it holds: the run
 * resumes on one body covering every deferred call, so a second submission would arrive
 * at a run that had already gone on. Hence one button here rather than one per panel.
 *
 * **STOP is not optional.** Taking over the composer takes away the only interrupt the
 * operator had, and a question — unlike an approval — has no "deny" to escape through.
 * Without it, a park the operator does not want to answer would be a trap.
 *
 * ── The glass, and three ways to lose it silently ──
 * The surface is `ConstructionReveal`'s (`ody-glass`), and it frosts the transcript
 * scrolling behind it. All three failures below render a slightly lighter panel rather
 * than an error, which is why they are written down; `FramedOverlay` carries the long
 * version of the same warnings.
 *   1. Nothing opaque may paint between the panel and the transcript — the composer's
 *      dock background is on the composer's branch only, not around this one.
 *   2. `backdrop-filter` only blurs within its backdrop root, and `opacity < 1` on ANY
 *      ancestor creates one. Nothing between here and the viewport may fade.
 *   3. The content carries no fill of its own; a `bg-*` inside stacks a second surface
 *      over the frosted one and paints the page out from behind it.
 */
export function ParkDock(props: {
  park: Park;
  onSubmit: (settlement: {
    decisions?: ApprovalDecision[];
    answers?: QuestionAnswer[];
  }) => void | Promise<void>;
  onStop: () => void;
  /** Whether a Plan panel is on screen to answer a submitted plan in. Set by the chat
   *  room, which has one; **left unset by every host that does not** — a compare pane
   *  has no viewport, and deferring to a panel that does not exist would leave the
   *  operator a plan they can only Stop. Where it is unset the plan is decided here,
   *  as an ordinary approval. */
  planInPanel?: boolean;
}): JSX.Element {
  const [decisions, setDecisions] = createSignal<ApprovalDecision[]>([]);
  const [allDecided, setAllDecided] = createSignal(false);
  const [replies, setReplies] = createSignal<Record<string, QuestionReply[]>>(
    {},
  );
  const [submitting, setSubmitting] = createSignal(false);

  /** A submitted plan is answered in the Plan panel where there is one, because a
   *  document is read at a panel's width and a decision docked at the far end of the
   *  window from its subject puts the question in two places. */
  const deferToPanel = () =>
    Boolean(props.planInPanel) && Boolean(props.park.planApproval);

  /** What this dock decides. The plan rejoins the list wherever no panel is holding
   *  it — the park is one park either way, and it resumes on one body. */
  const approvals = createMemo(() => {
    const plan = props.park.planApproval;
    return plan && !deferToPanel()
      ? [...props.park.approvals, plan]
      : props.park.approvals;
  });

  const hasApprovals = () => approvals().length > 0;
  const hasQuestions = () => props.park.questions.length > 0;
  /** Nothing left for the dock to ask: a park carrying `planApproval` carries nothing
   *  else (`stream/approvals.ts` splits it out only when it is the whole park), so
   *  deferring to the panel empties the dock. It stands down to its Stop control and
   *  points at the panel rather than putting a second, emptier copy of the question
   *  under it. */
  const planOnly = () => deferToPanel();

  /** Every question in the park answered — each with a selection or something written.
   *  The backend refuses a question answered with neither, so the button refuses first
   *  rather than sending a body that will come back 422. */
  const allAnswered = createMemo(() =>
    props.park.questions.every((q) => {
      const given = replies()[q.toolCallId];
      return (
        given?.length === q.questions.length &&
        given.every((r) => r.selections.length > 0 || (r.text ?? "").trim())
      );
    }),
  );

  const ready = () =>
    (!hasApprovals() || allDecided()) && (!hasQuestions() || allAnswered());

  const label = () =>
    hasQuestions() && hasApprovals()
      ? "Answer and decide"
      : hasQuestions()
        ? "Send answer"
        : "Submit decision";

  async function submit() {
    if (!ready() || submitting()) return;
    setSubmitting(true);
    try {
      await props.onSubmit({
        decisions: hasApprovals() ? decisions() : [],
        answers: props.park.questions.map((q) => ({
          tool_call_id: q.toolCallId,
          replies: replies()[q.toolCallId] ?? [],
        })),
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ConstructionReveal when origin="top-left" contentClass="flex flex-col">
      <Stack gap={3} class="p-4">
        <Show
          when={!props.park.stale}
          fallback={
            <Text variant="micro" tone="dim">
              ANSWERED ELSEWHERE — this was settled from another session; the
              transcript will catch up shortly.
            </Text>
          }
        >
          <Show when={planOnly()}>
            <Text variant="body" tone="bright">
              A plan is waiting for you in the Plan panel.
            </Text>
          </Show>

          <Show when={hasQuestions()}>
            <Stack gap={4}>
              <For each={props.park.questions}>
                {(question) => (
                  <QuestionPanel
                    question={question}
                    onChange={(given) =>
                      setReplies((current) => ({
                        ...current,
                        [question.toolCallId]: given,
                      }))
                    }
                  />
                )}
              </For>
            </Stack>
          </Show>

          <Show when={hasApprovals()}>
            <ApprovalPanel
              approvals={approvals()}
              // A plan decided in the dock is still a plan: the same three answers,
              // and still no recurring act for a standing grant to stand for.
              revisable={Boolean(props.park.planApproval)}
              hideGrant={Boolean(props.park.planApproval)}
              onChange={(given, decided) => {
                setDecisions(given);
                setAllDecided(decided);
              }}
            />
          </Show>

          <Row justify="between" align="center">
            {/* The way out. See the note above — this is the operator's only
                interrupt while the dock holds the composer's slot. */}
            <Button
              variant="ghost"
              size="sm"
              leading="close"
              onClick={props.onStop}
            >
              Stop
            </Button>
            {/* Nothing to submit when the panel owns the decision — a disabled button
                beside a question asked somewhere else reads as a dead end. */}
            <Show when={!planOnly()}>
              <Button
                variant="primary"
                disabled={!ready() || submitting()}
                onClick={submit}
              >
                {submitting() ? "Sending…" : label()}
              </Button>
            </Show>
          </Row>
        </Show>
      </Stack>
    </ConstructionReveal>
  );
}
