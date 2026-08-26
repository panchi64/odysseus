import {
  Show,
  createEffect,
  createSignal,
  onCleanup,
  onMount,
  type JSX,
} from "solid-js";
import { Portal } from "solid-js/web";
import { cx } from "../cx";
import { computePlacement, type Placement } from "./popoverPlacement";

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
  /** Horizontal alignment of the panel against the trigger. Default left. */
  align?: "left" | "right";
  /** Full-width field layout: the root fills its container and the panel spans the
   *  trigger's width (ignores `align`). Default inline/content. */
  block?: boolean;
  /** Extra classes for the panel (width, max-height, layout). */
  panelClass?: string;
  class?: string;
}

/** The dropdown shell shared by Menu, Select and Combobox: an anchored trigger, a
 *  click-out backdrop, and a floating panel. Owns open state and closes on backdrop
 *  click or Escape — the single home for that behavior.
 *
 *  **The panel is portalled to `document.body` and positioned `fixed`.** It used to be
 *  an `absolute` child of the trigger, which had two failure modes that looked like
 *  one: near the bottom of the window it ran off-screen, and inside any scroll
 *  container — the chat transcript, a modal body, the viewport panel — it was *clipped*
 *  by that ancestor's `overflow`, which no amount of `align` tuning could fix. A portal
 *  escapes every ancestor's overflow and stacking context; fixed coordinates measured
 *  from the trigger keep it anchored.
 *
 *  Placement flips above the trigger when there is more room there, and shifts
 *  horizontally to stay inside the viewport. It is recomputed on scroll (capture phase,
 *  so scroll containers fire it too, not just the window) and on resize. */
export function Popover(props: PopoverProps): JSX.Element {
  const [open, setOpen] = createSignal(false);
  const close = () => setOpen(false);

  let triggerRef: HTMLDivElement | undefined;
  let panelRef: HTMLDivElement | undefined;
  const [placement, setPlacement] = createSignal<Placement | null>(null);

  const measure = (): void => {
    if (!triggerRef) return;
    // Before the panel has rendered there is no height to flip on, so the first pass
    // places it below and a second (from the panel's own onMount) corrects it.
    const panel = panelRef?.getBoundingClientRect() ?? null;
    setPlacement(
      computePlacement({
        anchor: triggerRef.getBoundingClientRect(),
        panel,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        align: props.align,
        block: props.block,
      }),
    );
  };

  createEffect(() => {
    if (!open()) {
      setPlacement(null);
      return;
    }
    measure();
    // Capture phase: a scroll inside the transcript doesn't bubble to window, and that
    // is exactly the case the portal has to keep up with.
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    onCleanup(() => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    });
  });

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
    <div
      ref={triggerRef}
      class={cx(
        props.block ? "relative flex w-full" : "relative inline-flex",
        props.class,
      )}
    >
      {props.trigger({ open, setOpen, close })}
      <Show when={open()}>
        <Portal>
          <div class="fixed inset-0 z-40" onClick={close} />
          <PopoverPanel
            ref={(el) => {
              panelRef = el;
            }}
            placement={placement()}
            panelClass={props.panelClass}
            onMeasure={measure}
          >
            {props.panel({ close })}
          </PopoverPanel>
        </Portal>
      </Show>
    </div>
  );
}

/** Split out so `onMount` fires once the panel element exists — the first measure
 *  runs without a height (nothing is rendered yet) and this is what corrects it,
 *  before paint, so the panel never visibly jumps. */
function PopoverPanel(props: {
  ref: (el: HTMLDivElement) => void;
  placement: Placement | null;
  panelClass?: string;
  onMeasure: () => void;
  children: JSX.Element;
}): JSX.Element {
  onMount(() => props.onMeasure());
  return (
    <div
      ref={props.ref}
      class={cx(
        "fixed z-50 border border-line bg-surface",
        // Scrolling is added only when we actually clamp; Select already scrolls
        // itself and Combobox scrolls an inner element, and nesting a second
        // overflow-auto around either gives the panel two scrollbars.
        props.placement?.clampHeight != null &&
          "overflow-y-auto scrollbar-thin",
        props.panelClass,
      )}
      style={{
        top: `${props.placement?.top ?? 0}px`,
        left: `${props.placement?.left ?? 0}px`,
        "max-height":
          props.placement?.clampHeight != null
            ? `${props.placement.clampHeight}px`
            : undefined,
        width: props.placement?.width
          ? `${props.placement.width}px`
          : undefined,
        // Until the first measure lands the panel would flash at 0,0 in the corner.
        visibility: props.placement ? "visible" : "hidden",
      }}
    >
      {props.children}
    </div>
  );
}
