import { Show, type JSX } from "solid-js";
import { StatusFlag, Text, cx } from "~/ui";
import { relativeTime } from "~/lib/format";

export interface RecentThreadCardProps {
  title: string;
  preview?: string;
  model?: string;
  updatedAt: string;
  /** The resume target — the newest still-warm thread. */
  warm?: boolean;
  onOpen: () => void;
}

/** A recent-conversation preview tile for the overview launchpad. The warm
 *  thread carries a RESUME marker and a bright border so "where was I" is one
 *  glance and one click. */
export function RecentThreadCard(props: RecentThreadCardProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={() => props.onOpen()}
      class={cx(
        "flex w-full flex-col gap-1 border p-3 text-left transition-colors hover:bg-raised",
        props.warm ? "border-bright" : "border-line",
      )}
    >
      <div class="flex items-center justify-between gap-2">
        <Text
          variant="label"
          tone={props.warm ? "bright" : "default"}
          class="truncate"
        >
          {props.title}
        </Text>
        <Show
          when={props.warm}
          fallback={
            <Text variant="micro" tone="dim" class="shrink-0">
              {relativeTime(props.updatedAt)}
            </Text>
          }
        >
          <StatusFlag status="info">RESUME</StatusFlag>
        </Show>
      </div>
      <Show when={props.preview}>
        <Text variant="micro" tone="dim" class="truncate">
          {props.preview}
        </Text>
      </Show>
      <div class="flex items-center gap-2">
        <Show when={props.model}>
          <Text variant="micro" tone="dim">
            {props.model}
          </Text>
        </Show>
        <Show when={props.warm}>
          <Text variant="micro" tone="dim">
            {relativeTime(props.updatedAt)}
          </Text>
        </Show>
      </div>
    </button>
  );
}
