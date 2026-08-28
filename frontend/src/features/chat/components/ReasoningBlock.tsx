import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { Caret, Disclosure, Frames, Text, cx } from "~/ui";

/** Collapsible reasoning/thinking passage, rendered apart from the answer and
 *  dimmer than it (the answer is the bright value). Collapsed by default. The
 *  whole block is a click target, but a click that completes a text selection is
 *  ignored so the reasoning text stays selectable.
 *
 *  Open state, in precedence order:
 *  - `open` (expand-all / collapse-all) — when defined, wins.
 *  - `active` — the live, trailing reasoning block: auto-peeks its streaming
 *    tokens (capped height), then collapses the moment the next block appears.
 *  - otherwise closed-by-default, toggled locally. */
export function ReasoningBlock(props: {
  reasoning: string;
  open?: boolean;
  /** This is the turn's trailing block and the run is still going. */
  active?: boolean;
  /** Tokens are still streaming in (drives the THINKING throbber + caret). */
  streaming?: boolean;
}): JSX.Element {
  const [open, setOpen] = createSignal(false);

  // Adopt the controlling value when it changes; local toggles still work
  // between changes. `open` (explicit expand-all) wins; otherwise the live block
  // auto-peeks while active and collapses when it stops being active.
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
    else if (props.active !== undefined) setOpen(props.active);
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
    // The left rail is owned by the enclosing TurnBlocks Rail — this block just
    // carries the collapsible header + body.
    <div onClick={handleClick} class="cursor-pointer">
      {/* Controlled: the local signal above is the state, so the container's own
          click handler and the trigger stay in agreement. */}
      <Disclosure
        label={props.active ? "THINKING" : "REASONING"}
        open={open()}
        onToggle={toggle}
        trailing={
          <Show when={props.active && props.streaming}>
            <Frames class="text-info" />
          </Show>
        }
        // While active, peek the latest tokens: cap the height and pin to the
        // bottom (col-reverse) so the newest reasoning stays in view.
        class={cx(
          "mt-1",
          props.active && "flex max-h-32 flex-col-reverse overflow-hidden",
        )}
      >
        <Text
          variant="body"
          tone="dim"
          class="block cursor-text whitespace-pre-wrap"
        >
          {props.reasoning}
          <Show when={props.active && props.streaming}>
            <Caret />
          </Show>
        </Text>
      </Disclosure>
    </div>
  );
}
