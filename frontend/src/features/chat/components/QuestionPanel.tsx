import { createSignal, For, onMount, Show, type JSX } from "solid-js";
import { Checkbox, Stack, Text, Textarea, cx } from "~/ui";
import type { Question, QuestionReply } from "../model";

/**
 * **The agent asking, and the operator answering.** Every question in one parked call,
 * answered together — the run resumes on one submission, so a per-question submit would
 * be a button that could not do what it says.
 *
 * The written answer is always there, under every question, in both modes. That is the
 * point of the whole surface and not a fallback: the options are the model's guesses at
 * what the operator might say, never the range of what they are allowed to say. A form
 * that only offered the guesses would quietly convert "here is what I think you want"
 * into "choose one of these", which is a different and much worse question.
 *
 * No `RadioGroup` is extracted from this and `SessionModeSwitch`, despite both being
 * `role="radiogroup"`. They are not the same control wearing different paint: one is a
 * segmented row of icon chips that fits in a rail, the other a vertical list of labelled
 * choices with descriptions and an optional multi-select. What they share is four ARIA
 * attributes, and a component unifying them would have to carry both layouts behind a
 * variant flag to save repeating those.
 */
export function QuestionPanel(props: {
  question: Question;
  /** Collected upward on every change; the dock owns the submit for the whole park. */
  onChange: (replies: QuestionReply[]) => void;
}): JSX.Element {
  // Indexed by question position, matching the positional `replies` the backend expects.
  const [chosen, setChosen] = createSignal<Record<number, string[]>>({});
  const [written, setWritten] = createSignal<Record<number, string>>({});

  const emit = () => {
    props.onChange(
      props.question.questions.map((_, i) => ({
        selections: chosen()[i] ?? [],
        text: written()[i] || undefined,
      })),
    );
  };

  // Publish the (empty) reply set once on mount, so the dock always holds one reply per
  // question rather than nothing at all. Without it a call that parsed to *zero*
  // questions never emits — there is nothing to click — and the dock's "every question
  // answered" test compares `undefined` against 0 forever, leaving submit permanently
  // disabled with Stop as the only way out.
  onMount(emit);

  const pick = (index: number, label: string, multi: boolean) => {
    setChosen((current) => {
      const at = current[index] ?? [];
      if (!multi) return { ...current, [index]: [label] };
      return {
        ...current,
        [index]: at.includes(label)
          ? at.filter((l) => l !== label)
          : [...at, label],
      };
    });
    emit();
  };

  const isChosen = (index: number, label: string) =>
    (chosen()[index] ?? []).includes(label);

  return (
    <Stack gap={3}>
      <For each={props.question.questions}>
        {(q, index) => (
          <Stack gap={2}>
            <Text variant="body" tone="bright">
              {q.question}
            </Text>
            <div
              role={q.multiSelect ? "group" : "radiogroup"}
              aria-label={q.question}
              class="flex flex-col gap-1"
            >
              <For each={q.options}>
                {(option) => (
                  <Show
                    when={!q.multiSelect}
                    fallback={
                      <label
                        class={cx(
                          "flex cursor-pointer flex-col gap-0.5 rounded-ctl px-2 py-1.5 transition-colors hover:bg-raised",
                          isChosen(index(), option.label) && "bg-raised",
                        )}
                      >
                        <Checkbox
                          checked={isChosen(index(), option.label)}
                          onChange={() => pick(index(), option.label, true)}
                          label={option.label}
                        />
                        <Show when={option.description}>
                          <Text variant="micro" tone="dim" class="pl-6">
                            {option.description}
                          </Text>
                        </Show>
                      </label>
                    }
                  >
                    <button
                      type="button"
                      role="radio"
                      aria-checked={isChosen(index(), option.label)}
                      onClick={() => pick(index(), option.label, false)}
                      class={cx(
                        "flex flex-col items-start gap-0.5 rounded-ctl px-2 py-1.5 text-left transition-colors hover:bg-raised",
                        // Selection is a raised fill, the same way the rest of the
                        // system marks a current choice — not a coloured pill.
                        isChosen(index(), option.label) && "bg-raised",
                      )}
                    >
                      <Text
                        variant="label"
                        tone={
                          isChosen(index(), option.label) ? "bright" : "dim"
                        }
                      >
                        {option.label}
                      </Text>
                      <Show when={option.description}>
                        <Text variant="micro" tone="dim">
                          {option.description}
                        </Text>
                      </Show>
                    </button>
                  </Show>
                )}
              </For>
            </div>
            <Textarea
              rows={2}
              placeholder="Or write your own answer"
              value={written()[index()] ?? ""}
              onInput={(e) => {
                const text = e.currentTarget.value;
                setWritten((current) => ({ ...current, [index()]: text }));
                emit();
              }}
            />
          </Stack>
        )}
      </For>
    </Stack>
  );
}
