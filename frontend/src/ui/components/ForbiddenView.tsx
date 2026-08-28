import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";

export interface ForbiddenViewProps {
  /** Reason line. Defaults to a generic privilege message. */
  reason?: string;
  /** The privilege/area that was denied, shown as diegetic detail. */
  code?: string;
  class?: string;
  children?: JSX.Element;
}

/** Access-denied surface. Guards render this instead of a blank page when a
 *  privilege check fails (security model: deny visibly, never silently). */
export function ForbiddenView(props: ForbiddenViewProps): JSX.Element {
  const [local] = splitProps(props, ["reason", "code", "class", "children"]);
  return (
    <div
      class={cx(
        "flex min-h-[40vh] flex-col items-center justify-center gap-3 px-4 text-center",
        local.class,
      )}
    >
      <Icon name="lock" size={32} class="text-alert" />
      <Text variant="readout" tone="alert">
        ACCESS DENIED
      </Text>
      <Text variant="body" tone="dim">
        {local.reason ??
          "You do not have the privilege required to view this area."}
      </Text>
      <Show when={local.code}>
        <Text variant="micro" tone="dim">
          {local.code}
        </Text>
      </Show>
      <Show when={local.children}>{local.children}</Show>
    </div>
  );
}
