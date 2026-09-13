import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { Button, Composer, ConstructionReveal, Row, Stack, Text } from "~/ui";
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
 * **A submitted plan is decided here too.** It used to be handed to the Plan panel, on
 * the reasoning that a document is answered where it is read — but that put the one
 * decision the operator most has to think about in the one place no other decision lives,
 * left hosts without a panel unable to answer at all, and split a single park across two
 * surfaces. The panel still holds the plan; the dock still holds the answer, with a
 * button pointing at the panel for the reading.
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
  /** Put the Plan panel on screen, for a park holding a submitted plan. Left unset by
   *  hosts that have no viewport — a compare pane — where the card simply does not offer
   *  the button. */
  onReadPlan?: () => void;
}): JSX.Element {
  const [decisions, setDecisions] = createSignal<ApprovalDecision[]>([]);
  const [allDecided, setAllDecided] = createSignal(false);
  const [replies, setReplies] = createSignal<Record<string, QuestionReply[]>>(
    {},
  );
  const [submitting, setSubmitting] = createSignal(false);

  const hasApprovals = () => props.park.approvals.length > 0;
  const hasQuestions = () => props.park.questions.length > 0;

  /** Whether the operator has asked for changes rather than given a verdict.
   *
   *  Derived from the decisions rather than tracked beside them, and that is also what
   *  makes the composer need no Cancel of its own: the card's three buttons stay on
   *  screen above it, so changing one's mind back to Approve is the same click it always
   *  was and puts the ordinary submit button back. A Cancel here would be a second owner
   *  of an answer the card already holds, and the two would disagree the moment either
   *  moved. */
  const revising = createMemo(() =>
    decisions().some((d) => !d.approved && d.intent === "revise"),
  );

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

  /** Why the composer's SEND cannot settle this park yet, or null when it can.
   *
   *  The composer replaces the submit button while a revision is being written, so
   *  without this it would also replace the button's *disabled* state — and a park that
   *  held anything besides the plan would take the operator's note, refuse it in
   *  `submit`'s `ready()` guard, and say nothing about why. `sendBlocked` is the
   *  composer's own answer to "what you have is fine, but it would be refused": the
   *  field stays live, so the note being typed survives while the operator goes and
   *  answers the rest.
   *
   *  Unreachable today — plan mode withholds everything else that could defer, so a park
   *  carrying a plan carries nothing else. Written anyway, because the dead end it would
   *  leave has only Stop in it, and the cost of the guard is one string. */
  const sendBlocked = (): string | null =>
    ready()
      ? null
      : "This request settles in one go — answer the rest of it first.";

  /** Settle the whole park in one body. `note` is what the operator wrote in the
   *  composer, and it rides on every call they asked for changes to — the one kind of no
   *  that is a request rather than a refusal. */
  async function submit(note?: string): Promise<void> {
    if (!ready() || submitting()) return;
    setSubmitting(true);
    try {
      await props.onSubmit({
        decisions: hasApprovals()
          ? decisions().map((d) =>
              !d.approved && d.intent === "revise" && note
                ? { ...d, message: note }
                : d,
            )
          : [],
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
              approvals={props.park.approvals}
              onReadPlan={props.onReadPlan}
              onChange={(given, decided) => {
                setDecisions(given);
                setAllDecided(decided);
              }}
            />
          </Show>

          {/* Asking for changes is the one answer that needs words, so it borrows the
              operator's own input rather than growing a second one inside the card. The
              real `Composer`: Enter sends, the field autosizes, and SEND says what this
              particular send does. `bare` because it is sitting inside the dock's own
              surface, and no `storageKey` because a note about this plan is not a draft
              of the next message.

              **Only for a revision, and the asymmetry is the point.** A revision resumes
              the *same* turn straight into another draft — if the operator does not say
              what was wrong now, they never get to. A rejection ends it, and the composer
              they are handed back is the ordinary one, where saying why is just the next
              message. So the card that used to carry a textarea for both answers now
              stops the operator for the one that cannot wait. */}
          <Show when={revising()}>
            <Composer
              bare
              autofocus
              sendLabel="Revise"
              placeholder="What should change about this plan?"
              sendBlocked={sendBlocked()}
              onSend={(text) => void submit(text)}
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
            {/* While the note is being written, SEND is the composer's own — a second
                submit beside it would be two buttons doing one thing, one of which
                would post an empty request for changes. It carries the same refusal the
                button would have (`sendBlocked`), so hiding the button hides no state. */}
            <Show when={!revising()}>
              <Button
                variant="primary"
                disabled={!ready() || submitting()}
                onClick={() => void submit()}
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
