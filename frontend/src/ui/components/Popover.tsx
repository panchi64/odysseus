import {
  Show,
  createEffect,
  createSignal,
  onCleanup,
  type JSX,
} from "solid-js";
import { cx } from "../cx";

export interface PopoverApi {
  /** Reactive open-state accessor — call it (`open()`) in the trigger. */
  open: () => boolean;
  setOpen: (open: boolean) => void;
  close: () => void;
}

export interface PopoverProps {
  /** The clickable trigger; receives the open state + setters. */
  trigger: (api: PopoverApi) => JSX.Element;
  /** The floating panel contents; receives `close` to dismiss on select. */
  panel: (api: { close: () => void }) => JSX.Element;
  /** Horizontal alignment of the panel. Default left. */
  align?: "left" | "right";
  /** Extra classes for the panel (width, max-height, layout). */
  panelClass?: string;
  class?: string;
}

/** The dropdown shell shared by Menu and Combobox: an anchored trigger, a
 *  click-out backdrop, and an aligned floating panel. Owns open state and closes
 *  on backdrop click or Escape — the single home for that behavior. */
export function Popover(props: PopoverProps): JSX.Element {
  const [open, setOpen] = createSignal(false);
  const close = () => setOpen(false);

  // Escape closes while open (the backdrop handles outside clicks).
  createEffect(() => {
    if (!open()) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    onCleanup(() => document.removeEventListener("keydown", onKey));
  });

  return (
    <div class={cx("relative inline-flex", props.class)}>
      {props.trigger({ open, setOpen, close })}
      <Show when={open()}>
        <div class="fixed inset-0 z-40" onClick={close} />
        <div
          class={cx(
            "absolute top-full z-50 mt-1 border border-line bg-surface",
            props.align === "right" ? "right-0" : "left-0",
            props.panelClass,
          )}
        >
          {props.panel({ close })}
        </div>
      </Show>
    </div>
  );
}
