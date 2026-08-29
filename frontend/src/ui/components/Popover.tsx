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
  /** Drop the panel's own surface — no fill, no radius, no elevation — leaving only
   *  the positioning. For a panel that brings its own container (the framed, frosted
   *  region a `ConstructionReveal` draws): a card *around* that frame is the
   *  box-in-a-box the frame exists to avoid, and its shadow would sit on the glass. */
  bare?: boolean;
  /** Fired on the closed→open edge only, so a caller can refresh what the panel is
   *  about to show. Not fired on close, and never twice for one opening. */
  onOpen?: () => void;
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

  // The open edge, fired from the state change rather than the trigger's click
  // handler — the trigger is only one of the ways this opens, and a caller asking
  // "refresh when the panel appears" means whenever it appears.
  let wasOpen = false;
  createEffect(() => {
    const isOpen = open();
    if (isOpen && !wasOpen) props.onOpen?.();
    wasOpen = isOpen;
  });

  let triggerRef: HTMLDivElement | undefined;
  let panelRef: HTMLDivElement | undefined;
  const [placement, setPlacement] = createSignal<Placement | null>(null);

  const measure = (): void => {
    if (!triggerRef) return;
    // Before the panel has rendered there is no height to flip on, so the first pass
    // places it below and a second (from the panel's own onMount) corrects it.
    //
    // The measurement has to be of the panel's **natural** height, which is why the
    // inline `max-height` comes off first. Measuring through it feeds the previous
    // pass's clamp back in: a 400px panel clamped to 200 measures 200 next time, `200 >
    // 200` is false, the clamp is dropped, the panel springs open off-screen, and the
    // pass after that clamps it again — a visible flicker on every scroll, with the
    // flip decision oscillating alongside it because it reads the same height.
    let panel: { width: number; height: number } | null = null;
    if (panelRef) {
      const restore = panelRef.style.maxHeight;
      panelRef.style.maxHeight = "";
      const rect = panelRef.getBoundingClientRect();
      panel = { width: rect.width, height: rect.height };
      panelRef.style.maxHeight = restore;
    }
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
            bare={props.bare}
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
  bare?: boolean;
  onMeasure: () => void;
  children: JSX.Element;
}): JSX.Element {
  onMount(() => props.onMeasure());
  return (
    <div
      ref={props.ref}
      class={cx(
        "fixed z-50",
        // A bare panel also drops the rise: it brings its own arrival, and two
        // entrance animations on nested elements read as a bounce.
        !props.bare && "ody-rise rounded-panel bg-surface shadow-2",
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
        // A floor, not a fixed width: a `block` panel spans its field but grows to
        // fit its own options rather than truncating them (see `Placement.minWidth`).
        // Safe to measure through — unlike the max-height above, a min-width can only
        // widen the natural size, so re-measuring never feeds a shrinking value back.
        "min-width": props.placement?.minWidth
          ? `${props.placement.minWidth}px`
          : undefined,
        // Until the first measure lands the panel would flash at 0,0 in the corner.
        visibility: props.placement ? "visible" : "hidden",
      }}
    >
      {props.children}
    </div>
  );
}
