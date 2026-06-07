import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";

export interface RegistrationFrameProps {
  /** Show the corner registration crosses. Default true. */
  corners?: boolean;
  /** Optional diegetic ID printed bottom-left (e.g. "RCM-OB-01.3"). */
  assetId?: string;
  class?: string;
  children: JSX.Element;
}

/** Diegetic framing device: corner registration marks (§5/§7). Non-interactive
 *  atmosphere; use as a frame on full-screen layouts. */
export function RegistrationFrame(props: RegistrationFrameProps): JSX.Element {
  const [local] = splitProps(props, [
    "corners",
    "assetId",
    "class",
    "children",
  ]);
  const showCorners = () => local.corners ?? true;
  return (
    <div class={cx("relative", local.class)}>
      <Show when={showCorners()}>
        <Icon
          name="cross"
          size={10}
          class="pointer-events-none absolute left-1 top-1 text-dim"
        />
        <Icon
          name="cross"
          size={10}
          class="pointer-events-none absolute right-1 top-1 text-dim"
        />
        <Icon
          name="cross"
          size={10}
          class="pointer-events-none absolute bottom-1 left-1 text-dim"
        />
        <Icon
          name="cross"
          size={10}
          class="pointer-events-none absolute bottom-1 right-1 text-dim"
        />
      </Show>
      <Show when={local.assetId}>
        <span class="pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 text-micro uppercase tracking-label text-dim">
          {local.assetId}
        </span>
      </Show>
      {local.children}
    </div>
  );
}
