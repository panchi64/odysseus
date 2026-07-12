import { For, createEffect, createSignal, type JSX } from "solid-js";
import { Button, Panel, Row, Stack, Text, Textarea } from "~/ui";

interface ClarifyFormProps {
  questions: string[];
  submitting: boolean;
  /** A skip request (force straight to a plan) is in flight. */
  skipping: boolean;
  onSubmit: (answers: string[]) => void;
  /** The skip/start-now affordance (DR-1.6): forces `refine` straight to a
   *  plan without answering, reachable from every clarify round. */
  onSkip: () => void;
}

/** The clarify step of the pre-run flow (DR-1.6): a short form for the
 *  planner's up-to-a-few clarifying questions. Submitting re-runs `refine`,
 *  which may return more questions or move on to a plan — this component only
 *  renders whatever the caller currently has, never loops on its own. */
export function ClarifyForm(props: ClarifyFormProps): JSX.Element {
  const [answers, setAnswers] = createSignal<string[]>(
    props.questions.map(() => ""),
  );

  // A new clarify round (submitting answers can yield fresh questions rather
  // than a plan) must start blank — this instance persists across rounds, so
  // the signal is reset whenever the question set itself changes.
  createEffect(() => {
    const qs = props.questions;
    setAnswers(qs.map(() => ""));
  });

  const setAnswer = (index: number, value: string) => {
    setAnswers((prev) => prev.map((a, i) => (i === index ? value : a)));
  };

  const busy = () => props.submitting || props.skipping;

  return (
    <Panel label="A FEW QUESTIONS FIRST">
      <Stack gap={4}>
        <For each={props.questions}>
          {(q, i) => (
            <Stack gap={1}>
              <Text variant="label" tone="bright">
                {q}
              </Text>
              <Textarea
                rows={2}
                value={answers()[i()] ?? ""}
                onInput={(e) => setAnswer(i(), e.currentTarget.value)}
                placeholder="Your answer…"
              />
            </Stack>
          )}
        </For>
        <Row justify="between" align="center" gap={2}>
          <Button variant="default" disabled={busy()} onClick={props.onSkip}>
            SKIP QUESTIONS
          </Button>
          <Button
            variant="primary"
            leading="send"
            disabled={busy()}
            onClick={() => props.onSubmit(answers())}
          >
            SUBMIT ANSWERS
          </Button>
        </Row>
      </Stack>
    </Panel>
  );
}
