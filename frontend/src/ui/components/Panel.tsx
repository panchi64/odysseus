import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";

export type PanelState = "default" | "active" | "alert";

export interface PanelProps extends JSX.HTMLAttributes<HTMLElement> {
  /** Header bar label (uppercase). Omit for a headerless panel. */
  label?: string;
  /** Right-aligned header content: status flag, count, meta. */
  meta?: JSX.Element;
  /** Emphasis state. `active` = 2px bright border; `alert` = alert border. */
  state?: PanelState;
  /** Remove the default body padding (for edge-to-edge content like tables). */
  flush?: boolean;
}

const stateBorder: Record<PanelState, string> = {
  default: "border-line",
  active: "border-2 border-bright",
  alert: "border border-alert",
};

/** Bordered region with square corners and an optional header bar (§6.2). */
export function Panel(props: PanelProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "label",
    "meta",
    "state",
    "flush",
    "class",
    "children",
  ]);
  return (
    <section
      class={cx(
        "bg-surface border",
        stateBorder[local.state ?? "default"],
        local.class,
      )}
      {...rest}
    >
      <Show when={local.label || local.meta}>
        <header class="flex items-center justify-between gap-2 border-b border-line px-4 py-2">
          <Text variant="label" tone="dim">
            {local.label}
          </Text>
          <Show when={local.meta}>{local.meta}</Show>
        </header>
      </Show>
      <div class={cx(!local.flush && "p-4")}>{local.children}</div>
    </section>
  );
}
