import { For, Show, type JSX } from "solid-js";
import { Stack, Text } from "~/ui";
import type { AnsweredQuestion } from "../model";

/**
 * **What the agent asked, and what it was told** — the settled half of the dock, kept in
 * the transcript.
 *
 * It exists because the answer used to leave no readable trace. The question is asked in
 * a dock that takes over the composer and disappears the moment it is submitted, and the
 * only record afterwards was the `ask_user` call's own result: prose, rendered as a
 * generic tool row, inside a work log that folds shut. So a thread would read as the
 * agent asking nothing and then acting on something — the operator's own contribution to
 * the turn, missing from the account of it.
 *
 * **It is the agent's row, not the operator's.** Rendering the answers as a user bubble
 * was the obvious alternative and is worse: it would credit the operator with a message
 * they never typed, sitting in a transcript where every other user bubble is one they
 * did, and a reload would have to synthesise the same fiction to agree with itself.
 * What actually happened is that a call the agent made came back carrying their answer,
 * so it renders where that call is.
 *
 * **The question's own words come from the backend**, paired with the reply from the
 * parked call's arguments (warm, on `question.answered`; cold, from the same pairing in
 * the conversation projection). This component restates rather than re-derives, so a
 * reload cannot word a question differently from the way it was asked.
 */
export function QuestionAnswerCard(props: {
  answers: AnsweredQuestion[];
}): JSX.Element {
  return (
    <Stack gap={3} class="rounded-ctl border border-line bg-sunken px-3 py-2.5">
      <Text variant="label" tone="dim">
        Asked you
      </Text>
      <For each={props.answers}>
        {(answer) => (
          <Stack gap={1}>
            <Text variant="body" tone="dim">
              {answer.question}
            </Text>
            {/* The choice reads `bright`, because it is the operator's word in a row of
                the agent's. Where they chose nothing the written answer takes that
                position rather than sitting under an empty one — the options were the
                model's guesses, never the range of allowed replies, and a card implying
                otherwise would misreport what the surface offered. */}
            <Show
              when={answer.selections.length > 0}
              fallback={
                <Show when={answer.text}>
                  <Text variant="body" tone="bright">
                    {answer.text}
                  </Text>
                </Show>
              }
            >
              <Text variant="body" tone="bright">
                {answer.selections.join(", ")}
              </Text>
              <Show when={answer.text}>
                <Text variant="micro" tone="dim">
                  {answer.text}
                </Text>
              </Show>
            </Show>
          </Stack>
        )}
      </For>
    </Stack>
  );
}
