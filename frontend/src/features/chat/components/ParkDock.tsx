import { createMemo, createSignal, Show, type JSX } from "solid-js";
import { Button, Composer, ConstructionReveal, Row, Stack, Text } from "~/ui";
import type { Park, ParkDraft } from "../stream/approvals";
import type {
  ApprovalDecision,
  ChatMessage,
  QuestionAnswer,
  QuestionReply,
} from "../model";
import {
  allPagesAnswered,
  answersFor,
  pageAnswered,
  parkPages,
} from "../parkPages";
import { ApprovalPanel } from "./ApprovalPanel";
import { QueuedMessageList } from "./QueuedMessageList";
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
 * **One question at a time.** The park's questions are flattened across its calls and
 * walked a page at a time (`parkPages.ts`), with the approvals — already one batched
 * decision — as the last page. Stacked, a park of six questions was a wall of radio
 * buttons standing in front of a transcript the dock had already taken the composer
 * from, with nothing to say how much of it was left. Pagination is presentation only:
 * the submission is still one body, because the run still resumes once.
 *
 * **Nothing typed here is held by this component.** The draft lives on the controller
 * (`ParkDraft`), because the dock is mounted by a `Show` over the park and a park can
 * momentarily re-derive — a steering message arriving mid-park used to unmount this with
 * the operator's half-written answers inside it.
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
  /** What has been entered so far, and how to change it — held by the controller. */
  draft: ParkDraft;
  onDraft: (next: Partial<ParkDraft>) => void;
  onSubmit: (settlement: {
    decisions?: ApprovalDecision[];
    answers?: QuestionAnswer[];
  }) => void | Promise<void>;
  onStop: () => void;
  /** Messages the operator queued before the run parked. Listed here because the dock
   *  holds the slot they would otherwise be managed from, and because they land on the
   *  same resume as the answer — a park is the one moment both are in flight at once. */
  queued?: ChatMessage[];
  onEditQueued?: (queuedMessageId: string, text: string) => void;
  onWithdrawQueued?: (queuedMessageId: string) => void;
  onHoldQueued?: (queuedMessageId: string, held: boolean) => void;
  /** Put the Plan panel on screen, for a park holding a submitted plan. Left unset by
   *  hosts that have no viewport — a compare pane — where the card simply does not offer
   *  the button. */
  onReadPlan?: () => void;
}): JSX.Element {
  const pages = createMemo(() => parkPages(props.park));
  /** Clamped on read: a park can gain or lose a call while the dock is up (a stale
   *  reconciliation, a replay), and a remembered index past the end would render
   *  nothing at all rather than the last question. */
  const index = () =>
    Math.min(props.draft.page, Math.max(pages().length - 1, 0));
  const page = () => pages()[index()];
  const asking = () => {
    const at = page();
    return at?.kind === "question" ? at : undefined;
  };
  const isLast = () => index() >= pages().length - 1;
  const [submitting, setSubmitting] = createSignal(false);

  const setReply = (callId: string, at: number, reply: QuestionReply) => {
    const current = props.draft.replies[callId] ?? [];
    const next = [...current];
    next[at] = reply;
    props.onDraft({
      replies: { ...props.draft.replies, [callId]: next },
    });
  };

  /** Whether the operator has asked for changes rather than given a verdict.
   *
   *  Derived from the decisions rather than tracked beside them, and that is also what
   *  makes the composer need no Cancel of its own: the card's three buttons stay on
   *  screen above it, so changing one's mind back to Approve is the same click it always
   *  was and puts the ordinary submit button back. A Cancel here would be a second owner
   *  of an answer the card already holds, and the two would disagree the moment either
   *  moved. */
  const revising = createMemo(() =>
    props.draft.decisions.some((d) => !d.approved && d.intent === "revise"),
  );

  const ready = createMemo(() =>
    allPagesAnswered(pages(), props.draft.replies, props.draft.allDecided),
  );
  const canAdvance = () =>
    page() !== undefined &&
    pageAnswered(page(), props.draft.replies, props.draft.allDecided);

  const label = () =>
    props.park.questions.length > 0 && props.park.approvals.length > 0
      ? "Answer and decide"
      : props.park.questions.length > 0
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
        decisions:
          props.park.approvals.length > 0
            ? props.draft.decisions.map((d) =>
                !d.approved && d.intent === "revise" && note
                  ? { ...d, message: note }
                  : d,
              )
            : [],
        answers: answersFor(props.park, props.draft.replies),
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
          {/* What the operator queued before the run stopped to ask. It is listed
              first because it is context for the answer rather than part of it: a
              message written a minute ago may be what the agent is now asking about,
              and it will reach the model on the same resume this answer does. Without
              it the queue is invisible from the one surface the operator is looking at
              — the dock has taken the slot its bubbles are normally managed from. */}
          <Show when={props.queued?.length}>
            <QueuedMessageList
              messages={props.queued ?? []}
              onEdit={props.onEditQueued}
              onWithdraw={props.onWithdrawQueued}
              onHold={props.onHoldQueued}
            />
          </Show>

          {/* Where the operator is, when there is more than one place to be. A single
              question says nothing — a position readout over one item is furniture. */}
          <Show when={pages().length > 1}>
            <Row justify="between" align="center">
              <Text variant="micro" tone="dim">
                {page()?.kind === "approvals"
                  ? `Step ${index() + 1} of ${pages().length} — permissions`
                  : `Question ${index() + 1} of ${pages().length}`}
              </Text>
              <Row gap={1} align="center">
                <Button
                  variant="ghost"
                  size="sm"
                  leading="chevron-left"
                  disabled={index() === 0}
                  onClick={() => props.onDraft({ page: index() - 1 })}
                >
                  Back
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  trailing="chevron-right"
                  disabled={isLast() || !canAdvance()}
                  onClick={() => props.onDraft({ page: index() + 1 })}
                >
                  Next
                </Button>
              </Row>
            </Row>
          </Show>

          <Show when={asking()}>
            {(at) => (
              <QuestionPanel
                question={at().question}
                reply={props.draft.replies[at().callId]?.[at().index]}
                onChange={(reply) => setReply(at().callId, at().index, reply)}
              />
            )}
          </Show>

          {/* **Mounted for the life of the dock, hidden off its page**, where a question
              is mounted only on its own. The asymmetry is not a style choice: a question
              is stateless here (its reply lives in the draft, so remounting it costs
              nothing), while the approval cards hold their own verdicts and grant ticks
              and publish them *on change*. Unmounted on the way to another page, they
              come back blank while the draft still says decided — cards showing nothing
              chosen above an enabled submit — and the next click would rebuild the batch
              from that empty state, dropping every verdict beside it. */}
          <Show when={props.park.approvals.length > 0}>
            <div classList={{ hidden: page()?.kind !== "approvals" }}>
              <ApprovalPanel
                approvals={props.park.approvals}
                onReadPlan={props.onReadPlan}
                onChange={(given, decided) =>
                  props.onDraft({ decisions: given, allDecided: decided })
                }
              />
            </div>
          </Show>

          {/* Asking for changes is the one answer that needs words, so it borrows the
              operator's own input rather than growing a second one inside the card. The
              real `Composer`: ⌘/Ctrl+Enter sends, the field autosizes, and SEND says what this
              particular send does. `bare` because it is sitting inside the dock's own
              surface, and no `storageKey` because a note about this plan is not a draft
              of the next message.

              **Only for a revision, and the asymmetry is the point.** A revision resumes
              the *same* turn straight into another draft — if the operator does not say
              what was wrong now, they never get to. A rejection ends it, and the composer
              they are handed back is the ordinary one, where saying why is just the next
              message. So the card that used to carry a textarea for both answers now
              stops the operator for the one that cannot wait. */}
          <Show when={revising() && isLast()}>
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
                button would have (`sendBlocked`), so hiding the button hides no state.

                The submit only appears on the last page: offering it earlier would put
                a disabled primary button under every question, which reads as the form
                being broken rather than as unfinished. */}
            <Show when={!revising() && isLast()}>
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
