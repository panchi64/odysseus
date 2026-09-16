/**
 * A park, cut into pages — one question at a time.
 *
 * The dock used to render every parked call stacked in one column, each call looping over
 * its own one-to-four questions. Two calls asking three questions each is six blocks of
 * radio buttons standing over the transcript, and the dock takes the composer's slot, so
 * the operator could not scroll past it to re-read what the agent had actually said. A
 * park is a queue of things to answer; a queue with no position is a wall.
 *
 * **One question per page, flattened across calls**, because the call is not a unit the
 * operator has any reason to perceive. They are answering questions; whether the model
 * asked them in one `ask_user` or three is a fact about the model's turn, and paging by
 * it would make one page a single line and the next three screens.
 *
 * **Approvals are the last page, together.** They are already answered as one batch on
 * one card, and a park holding both is rare (plan mode withholds everything else that
 * could defer) — so splitting the batch would cost the card its shared decision to buy
 * pagination nobody reaches.
 *
 * Pure data → data, like `blocks.ts` and `workShape.ts`: the rule is testable without a
 * DOM, and the dock is left holding only markup. Note what it does *not* change — the
 * whole park still submits in **one** body, because the run resumes once. Pagination is
 * presentation over a batch, never a way to send half of it.
 */

import type { Park } from "./stream/approvals";
import type { QuestionReply, QuestionSpec } from "./model";

/** One question, and where its reply is filed. */
export interface QuestionPage {
  kind: "question";
  /** The parked call it belongs to. */
  callId: string;
  /** Its position within that call — the index of its reply, positionally, which is how
   *  the backend reads the submission back against the parked arguments. */
  index: number;
  question: QuestionSpec;
}

/** Every approval in the park, decided as one. */
export interface ApprovalsPage {
  kind: "approvals";
}

export type ParkPage = QuestionPage | ApprovalsPage;

/** The park as an ordered list of pages: its questions in the order they were asked,
 *  then the approvals if it holds any. Empty only for a park holding nothing, which the
 *  dock never renders. */
export function parkPages(park: Park): ParkPage[] {
  const pages: ParkPage[] = [];
  for (const call of park.questions)
    call.questions.forEach((question, index) =>
      pages.push({
        kind: "question",
        callId: call.toolCallId,
        index,
        question,
      }),
    );
  if (park.approvals.length > 0) pages.push({ kind: "approvals" });
  return pages;
}

/** Whether one reply says anything at all.
 *
 *  The backend refuses a question answered with neither a selection nor words, so this
 *  is the same test made early — the operator is stopped by a disabled control rather
 *  than by a 422 arriving after they pressed send. */
export function isAnswered(reply: QuestionReply | undefined): boolean {
  return Boolean(
    reply && (reply.selections.length > 0 || (reply.text ?? "").trim()),
  );
}

/** Whether the operator has finished with this page — the gate on Next, and on the
 *  submit when it is the last one. */
export function pageAnswered(
  page: ParkPage,
  replies: Record<string, QuestionReply[]>,
  allDecided: boolean,
): boolean {
  if (page.kind === "approvals") return allDecided;
  return isAnswered(replies[page.callId]?.[page.index]);
}

/** Whether the whole park can be submitted.
 *
 *  Over the **pages**, not over the park, and the difference is a real case: a malformed
 *  `ask_user` can parse to zero questions, which produces no page and nothing to click.
 *  Counting replies against the call would then compare `undefined` to 0 forever and
 *  leave submit disabled with Stop as the only way out. A call with nothing in it is
 *  answered by definition, and `answersFor` still sends its empty reply list so the body
 *  covers every parked call. */
export function allPagesAnswered(
  pages: ParkPage[],
  replies: Record<string, QuestionReply[]>,
  allDecided: boolean,
): boolean {
  return pages.every((page) => pageAnswered(page, replies, allDecided));
}

/** The answers half of the submission: one entry per parked call, its replies
 *  positional and padded, so a call the operator never had a page for still appears. */
export function answersFor(
  park: Park,
  replies: Record<string, QuestionReply[]>,
): { tool_call_id: string; replies: QuestionReply[] }[] {
  return park.questions.map((call) => ({
    tool_call_id: call.toolCallId,
    replies: call.questions.map(
      (_, i) =>
        replies[call.toolCallId]?.[i] ?? { selections: [], text: undefined },
    ),
  }));
}
