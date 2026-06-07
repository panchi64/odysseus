import { Show, createSignal, type JSX } from "solid-js";
import { Icon, Text } from "~/ui";

/** Collapsible reasoning/thinking stream, rendered apart from the answer and
 *  dimmer than it (the answer is the bright value). Collapsed by default. */
export function ReasoningBlock(props: { reasoning: string }): JSX.Element {
  const [open, setOpen] = createSignal(false);
  return (
    <div class="border-l border-line pl-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        class="flex items-center gap-1 text-left text-dim transition-colors hover:text-text"
      >
        <Icon name={open() ? "chevron-down" : "chevron-right"} size={12} />
        <Text variant="label" tone="dim">
          REASONING
        </Text>
      </button>
      <Show when={open()}>
        <Text variant="body" tone="dim" class="mt-1 block whitespace-pre-wrap">
          {props.reasoning}
        </Text>
      </Show>
    </div>
  );
}
