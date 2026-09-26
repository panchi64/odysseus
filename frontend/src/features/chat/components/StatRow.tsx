import { children, Show, type JSX } from "solid-js";
import { Text } from "~/ui";

/** One labelled figure in the conversation's stats panel: what it is, its value, and a
 *  line saying what the value means.
 *
 *  **The explanation is printed, not hovered.** These figures used to be a line of
 *  terse segments under the composer, each carrying its meaning in a tooltip —
 *  `TTFT avg 20.5s` is four words the operator has to already know. A tooltip was the
 *  right weight for a readout that had to stay one line; in a panel the operator opened
 *  on purpose, a sentence they must point at to read is a sentence withheld.
 *
 *  Shared by the panel's settings rows (grants, auto-compaction) so a setting and a
 *  figure read as one list, with `children` for the control a setting carries. */
export function StatRow(props: {
  label: string;
  /** Absent for a row whose body is its control (`children`) rather than a figure. */
  value?: JSX.Element;
  hint: string;
  children?: JSX.Element;
}): JSX.Element {
  // Resolved once each: a JSX prop read twice — once to test it, once to render it —
  // would build its elements twice.
  const value = children(() => props.value);
  const control = children(() => props.children);
  return (
    <div class="flex flex-col gap-0.5">
      <div class="flex items-baseline justify-between gap-3">
        <Text variant="label" tone="dim" class="shrink-0">
          {props.label}
        </Text>
        <Show when={value()}>
          <Text
            variant="micro"
            tone="bright"
            class="min-w-0 text-right tabular-nums"
          >
            {value()}
          </Text>
        </Show>
      </div>
      <Text variant="micro" tone="dim">
        {props.hint}
      </Text>
      <Show when={control()}>
        <div class="pt-1">{control()}</div>
      </Show>
    </div>
  );
}
