import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { Icon, Text } from "~/ui";

/** Collapsible reasoning/thinking stream, rendered apart from the answer and
 *  dimmer than it (the answer is the bright value). Collapsed by default.
 *  The whole block is a click target, but a click that completes a text
 *  selection is ignored so the reasoning text stays selectable.
 *
 *  `open` makes it controlled (expand-all/collapse-all). When defined it syncs
 *  the local signal; when undefined the block keeps its closed-by-default
 *  behavior and toggles locally. */
export function ReasoningBlock(props: {
  reasoning: string;
  open?: boolean;
}): JSX.Element {
  const [open, setOpen] = createSignal(false);

  // Adopt the controlling value whenever it changes; local toggles still work
  // between changes (so a controlled-then-nudged block stays responsive).
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
  });

  const toggle = (): void => {
    setOpen((v) => !v);
  };

  // Ignore the click that finishes a drag-select so text can be highlighted.
  const handleClick = (): void => {
    if (window.getSelection()?.toString()) return;
    toggle();
  };

  return (
    <div
      onClick={handleClick}
      class="cursor-pointer border-l border-line pl-2 transition-colors hover:border-text/40"
    >
      <button
        type="button"
        onClick={(e) => {
          // The container handler owns toggling; keep the button's keyboard
          // activation working without double-firing on pointer clicks.
          e.stopPropagation();
          toggle();
        }}
        class="flex items-center gap-1 text-left text-dim transition-colors hover:text-text"
      >
        <Icon name={open() ? "chevron-down" : "chevron-right"} size={12} />
        <Text variant="label" tone="dim">
          REASONING
        </Text>
      </button>
      <Show when={open()}>
        <Text
          variant="body"
          tone="dim"
          class="mt-1 block cursor-text whitespace-pre-wrap"
        >
          {props.reasoning}
        </Text>
      </Show>
    </div>
  );
}
