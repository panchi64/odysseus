import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { Collapse, StatusFlag, Text } from "~/ui";
import type { Review } from "../model";
import { toolPresentation } from "../toolPresentation";
import { ProcessRow, Sep } from "./ProcessRow";

/** The verdict in the operator's words, as the row's own second segment.
 *
 *  Words rather than only a tone, because this is the one row in a turn whose whole
 *  content is a decision somebody else made on the operator's behalf — and a decision
 *  carried by colour alone is a decision they can scroll past (§12). Undefined is a real
 *  live state: the row appears when the review starts, so a review that costs a model call
 *  reads as work in flight instead of as a stalled turn. */
const VERDICT: Record<NonNullable<Review["decision"]>, string> = {
  allow: "allowed without asking you",
  ask: "handed to you",
  block: "refused",
};

/** Which stage settled it, spelled out. The distinction is the operator's to act on: a
 *  call cleared by the allowlist means the rule is too broad, and one cleared by the
 *  reviewer means the model judged it — two different things to go and change. */
const STAGE: Record<NonNullable<Review["stage"]>, string> = {
  judge: "Settled by the read-only allowlist, with no model call.",
  reviewer: "Settled by the reviewer.",
};

const RISK: Record<NonNullable<Review["risk"]>, string> = {
  low: "Low risk",
  high: "High risk",
  too_destructive: "Cannot be undone",
};

const AUTHORIZATION: Record<NonNullable<Review["authorization"]>, string> = {
  explicitly_no: "you refused it",
  neutral: "you neither asked for it nor refused it",
  explicitly_yes: "you asked for it",
};

/** One action the chassis ruled on in the operator's place, at the Auto permission level.
 *
 *  **It shares the rail's anatomy and refuses its card**, exactly as the injection row
 *  does and for the same reason: every row on a raised `bg-surface` panel is something the
 *  *model* did, and this is not. The model asked; we answered for the operator. Sitting
 *  flat on the page beside the call it judged is what says that at a glance, before a word
 *  of the row is read.
 *
 *  **A refusal is the one state that gets a flag.** A cleared call is followed by the call
 *  itself and a parked one by an approval card, so both are accounted for by the row after
 *  them. A refused call is followed by nothing at all — this row is the entire record of
 *  it, and it is the single thing in a turn an operator is most likely to disagree with.
 *
 *  `open` makes expand/collapse controlled (expand-all/collapse-all); at rest the row is
 *  closed, because the verdict is on the row and only the grounds are behind it. */
export function ReviewCard(props: {
  review: Review;
  open?: boolean;
}): JSX.Element {
  const [open, setOpen] = createSignal(false);
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
  });
  const judged = () => toolPresentation(props.review.name).label;
  const verdict = () =>
    props.review.decision ? VERDICT[props.review.decision] : "checking…";
  return (
    <div class="group/review">
      {/* No `hover:bg-raised`: that is what a row sitting on its own card gets, and this
          one deliberately has none — the same posture the injection row takes. */}
      <ProcessRow
        open={open()}
        onToggle={() => setOpen((v) => !v)}
        icon="review"
        iconClass={
          props.review.decision === "block" ? "text-alert" : "text-dim"
        }
        label="Review"
        title={`Review of ${props.review.name}`}
        trailing={
          <Show when={props.review.decision === "block"}>
            <StatusFlag status="alert">Refused</StatusFlag>
          </Show>
        }
      >
        <Sep />
        <Text variant="micro" tone="dim" class="min-w-0 shrink-0">
          {judged()}
        </Text>
        <Sep />
        <Text variant="micro" tone="dim" class="min-w-0 truncate">
          {verdict()}
        </Text>
      </ProcessRow>
      <Collapse open={open()}>
        <div class="flex flex-col gap-1 px-2 py-1.5">
          {/* What the action would do at its worst — the same sentence the reviewer was
              judging, so the operator and the model looked at one description. */}
          <Text variant="micro" tone="default" class="break-words">
            {props.review.summary}
          </Text>
          <Show when={props.review.stage}>
            {(stage) => (
              <Text variant="micro" tone="dim">
                {STAGE[stage()]}
              </Text>
            )}
          </Show>
          <Show when={props.review.risk}>
            {(risk) => (
              <Text variant="micro" tone="dim">
                {RISK[risk()]}
                <Show when={props.review.authorization}>
                  {(authorization) => (
                    <>, and {AUTHORIZATION[authorization()]}.</>
                  )}
                </Show>
              </Text>
            )}
          </Show>
          {/* Never a veto — an observation the operator reads. A reviewer that could
              refuse on "this looks like the wrong path" would be second-guessing the
              model's work rather than ruling on its permission. */}
          <Show when={props.review.correctness}>
            {(correctness) => (
              <Text variant="micro" tone="warn">
                {correctness()}
              </Text>
            )}
          </Show>
        </div>
      </Collapse>
    </div>
  );
}
