import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";

export interface PageHeaderProps {
  /** Section title (rendered in the display face). */
  title: string;
  /** Dim subtitle / description under the title. */
  subtitle?: string;
  /** Diegetic asset/version ID shown above the title (e.g. "RCM-OB-01.3"). */
  assetId?: string;
  /** Right-aligned actions (buttons, status flags). */
  actions?: JSX.Element;
  class?: string;
}

/** Standard screen header: every feature screen opens with one. The single
 *  per-screen `display` title lives here. */
export function PageHeader(props: PageHeaderProps): JSX.Element {
  const [local] = splitProps(props, [
    "title",
    "subtitle",
    "assetId",
    "actions",
    "class",
  ]);
  return (
    <header
      class={cx(
        "flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3",
        local.class,
      )}
    >
      <div class="flex flex-col gap-1">
        <Show when={local.assetId}>
          <Text variant="micro" tone="dim">
            {local.assetId}
          </Text>
        </Show>
        <Text variant="display" tone="bright" as="h1">
          {local.title}
        </Text>
        <Show when={local.subtitle}>
          <Text variant="body" tone="dim">
            {local.subtitle}
          </Text>
        </Show>
      </div>
      <Show when={local.actions}>
        <div class="flex items-center gap-2">{local.actions}</div>
      </Show>
    </header>
  );
}
