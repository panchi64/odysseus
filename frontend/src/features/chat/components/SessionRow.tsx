import { Show, type JSX } from "solid-js";
import { Icon, Text, TypewriterText, cx } from "~/ui";
import { REVEAL_SPEED_MS } from "../data";

export interface SessionRowProps {
  title: string;
  /** Right-aligned meta, e.g. relative time. */
  meta: string;
  selected?: boolean;
  pinned?: boolean;
  /** A freshly auto-generated title to type out in place of the static one. The
   *  header owns clearing the reveal; the row just mirrors it while it lasts. */
  reveal?: string;
  onOpen: () => void;
  onTogglePin: () => void;
}

/**
 * A selectable session row with an independent pin toggle. The label and the
 * pin are sibling buttons (not nested) so neither swallows the other's click.
 * The pin is revealed on hover/focus unless the row is already pinned.
 */
export function SessionRow(props: SessionRowProps): JSX.Element {
  return (
    <div
      class={cx(
        "group flex items-center border-b border-line transition-colors hover:bg-raised",
        props.selected && "bg-raised",
      )}
    >
      <button
        type="button"
        onClick={() => props.onOpen()}
        class="flex min-w-0 flex-1 items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <Show
          when={props.reveal}
          fallback={
            <Text
              variant="label"
              tone={props.selected ? "bright" : "default"}
              class="truncate"
            >
              {props.title}
            </Text>
          }
        >
          {(reveal) => (
            <TypewriterText
              variant="label"
              tone={props.selected ? "bright" : "default"}
              text={reveal()}
              speed={REVEAL_SPEED_MS}
              class="truncate"
            />
          )}
        </Show>
        <Text variant="micro" tone="dim" class="shrink-0">
          {props.meta}
        </Text>
      </button>
      <button
        type="button"
        onClick={() => props.onTogglePin()}
        aria-label={props.pinned ? "Unpin thread" : "Pin thread"}
        aria-pressed={props.pinned}
        class={cx(
          "shrink-0 px-2 py-2 transition-colors hover:text-bright",
          props.pinned
            ? "text-bright"
            : "text-dim opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
        )}
      >
        <Icon name="pin" size={12} />
      </button>
    </div>
  );
}
