import { For, Show, type JSX } from "solid-js";
import { Checkbox, Stack, Text, Textarea, cx } from "~/ui";
import type { QuestionReply, QuestionSpec } from "../model";

/**
 * **The agent asking, and the operator answering** — one question, on its own page.
 *
 * It used to render a whole parked call, looping over its one-to-four questions, while
 * the dock looped again over the calls. Two loops meant a park could stand six blocks of
 * radio buttons over a transcript the dock had already taken the composer from. The
 * sequence is `parkPages.ts`'s now, and what is left here is one question — which is also
 * the only thing this file was ever really about.
 *
 * The written answer is always there, under every question, in both modes. That is the
 * point of the whole surface and not a fallback: the options are the model's guesses at
 * what the operator might say, never the range of what they are allowed to say. A form
 * that only offered the guesses would quietly convert "here is what I think you want"
 * into "choose one of these", which is a different and much worse question.
 *
 * It holds no state. The reply lives with the rest of the park's draft on the controller,
 * because the dock is mounted by a `Show` and anything kept inside it is lost to a
 * re-render — which is exactly what a steering message arriving mid-park used to cause.
 *
 * No `RadioGroup` is extracted from this and `SessionModeSwitch`, despite both being
 * `role="radiogroup"`. They are not the same control wearing different paint: one is a
 * segmented row of icon chips that fits in a rail, the other a vertical list of labelled
 * choices with descriptions and an optional multi-select. What they share is four ARIA
 * attributes, and a component unifying them would have to carry both layouts behind a
 * variant flag to save repeating those.
 */
export function QuestionPanel(props: {
  question: QuestionSpec;
  /** What has been said to it so far, from the park's draft. */
  reply: QuestionReply | undefined;
  onChange: (reply: QuestionReply) => void;
}): JSX.Element {
  const selections = (): string[] => props.reply?.selections ?? [];
  const written = (): string => props.reply?.text ?? "";

  const pick = (label: string) => {
    const at = selections();
    const next = !props.question.multiSelect
      ? [label]
      : at.includes(label)
        ? at.filter((l) => l !== label)
        : [...at, label];
    props.onChange({ selections: next, text: props.reply?.text });
  };

  const isChosen = (label: string) => selections().includes(label);

  return (
    <Stack gap={2}>
      <Text variant="body" tone="bright">
        {props.question.question}
      </Text>
      <div
        role={props.question.multiSelect ? "group" : "radiogroup"}
        aria-label={props.question.question}
        class="flex flex-col gap-1"
      >
        <For each={props.question.options}>
          {(option) => (
            <Show
              when={!props.question.multiSelect}
              fallback={
                <label
                  class={cx(
                    "flex cursor-pointer flex-col gap-0.5 rounded-ctl px-2 py-1.5 transition-colors hover:bg-raised",
                    isChosen(option.label) && "bg-raised",
                  )}
                >
                  <Checkbox
                    checked={isChosen(option.label)}
                    onChange={() => pick(option.label)}
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
                aria-checked={isChosen(option.label)}
                onClick={() => pick(option.label)}
                class={cx(
                  "flex flex-col items-start gap-0.5 rounded-ctl px-2 py-1.5 text-left transition-colors hover:bg-raised",
                  // Selection is a raised fill, the same way the rest of the
                  // system marks a current choice — not a coloured pill.
                  isChosen(option.label) && "bg-raised",
                )}
              >
                <Text
                  variant="label"
                  tone={isChosen(option.label) ? "bright" : "dim"}
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
        value={written()}
        onInput={(e) =>
          props.onChange({
            selections: selections(),
            text: e.currentTarget.value,
          })
        }
      />
    </Stack>
  );
}
