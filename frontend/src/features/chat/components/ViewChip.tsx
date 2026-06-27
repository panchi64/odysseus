import { Show, type JSX } from "solid-js";
import { Icon, StatusFlag, Text, cx, type IconName } from "~/ui";

/**
 * A compact, clickable marker in the transcript for something the agent put in the
 * conversation's View — a snapshot version or the live head. Clicking opens it in
 * the viewport, so the transcript stays a readable narrative while the heavy render
 * lives beside it (and older versions stay reachable from where they happened).
 */
export function ViewChip(props: {
  icon: IconName;
  label: string;
  live?: boolean;
  onOpen: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={() => props.onOpen()}
      class={cx(
        "group/chip flex w-full items-center gap-2 border border-line bg-surface",
        "px-3 py-2 text-left transition-colors hover:border-bright",
      )}
    >
      <Icon
        name={props.icon}
        size={14}
        class="shrink-0 text-dim transition-colors group-hover/chip:text-text"
      />
      <Text variant="label" tone="default">
        VIEW
      </Text>
      <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
        {props.label}
      </Text>
      <Show when={props.live}>
        <StatusFlag status="live" dot pulse>
          LIVE
        </StatusFlag>
      </Show>
      <Icon
        name="chevron-right"
        size={14}
        class="shrink-0 text-dim transition-colors group-hover/chip:text-bright"
      />
    </button>
  );
}
