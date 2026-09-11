import { Show, type JSX } from "solid-js";
import {
  Button,
  ConstructionReveal,
  ResizeHandle,
  Reveal,
  Text,
  cx,
} from "~/ui";
import { emptyLayout } from "../viewport/layout";
import { surfaceSpec } from "../viewport/surfaces";
import type { ChatViewport } from "../useChatViewport";
import { ViewportHost } from "./ViewportHost";

export interface ChatViewportMountsProps {
  viewport: ChatViewport;
}

/**
 * Where the viewport sits, and how it gets there.
 *
 * Above `lg` it is a resizable aside beside the conversation; below `lg`, or in
 * fullscreen at any width, the same region covers the screen. Those are two
 * presentations of one thing, and this file's job is to make sure they stay one
 * thing.
 *
 * **The host mounts once and changes its box, rather than being swapped between
 * two mounts.** It used to be two branches — an aside, and a `Portal`ed sheet —
 * with the panel's JSX built by a function called in each. Only one was ever
 * mounted, so nothing looked wrong, but pressing `f` moved between them, which
 * meant tearing the panel down and building a new one: a live preview reloaded
 * its iframe mid-session, scroll position was lost, and every surface's local
 * state went back to its default. Expanding something to look at it more closely
 * is the worst possible moment to reload it.
 *
 * So there is one gate, one element, and the difference between the two
 * presentations is the classes on it. The `ConstructionReveal` is gated on
 * `shown()` rather than on either presentation, so the flip never crosses its
 * mount boundary.
 *
 * **No `Portal`, for the same reason.** Portalling moves a node to the document
 * body, and a node cannot be both in the row's flex flow and in the body — so
 * the portal *was* the branch. Fixed positioning covers the screen from where it
 * already is; nothing between here and the viewport clips or transforms, which
 * is the only thing a portal would have been buying.
 *
 * What goes *inside* is not this file's business. It hands the layout to
 * `ViewportHost` and the host asks the registry what to draw, so a new surface
 * never reaches here.
 *
 * **Resolve and dissolve at full width — an *animation*, not a transition.** The
 * difference is mechanism rather than taste: a transition needs a previous computed
 * value, and a region that mounts the instant it is opened has none, so it would
 * appear at its end state. `ConstructionReveal` rather than `Reveal` because the
 * viewport is a region the operator deliberately opens, so it is *built* — a `+`
 * splits, travels the top edge, drops down the sides, and the glass resolves inside
 * the frame it just described.
 */
export function ChatViewportMounts(
  props: ChatViewportMountsProps,
): JSX.Element {
  const sheet = () => props.viewport.sheetOpen();
  /** What the sheet calls itself: the surface being worked in. "Viewport" is the
   *  honest fallback for the moment before anything is focused — it is the panel
   *  as a whole that is covering the screen. */
  const sheetTitle = (): string => {
    const focused = props.viewport.focusedSurface();
    return focused === null ? "Viewport" : surfaceSpec(focused).label;
  };
  const toggleFullscreen = () => props.viewport.toggleFullscreen();

  // One close, dispatched on how the panel is currently presented. Leaving the
  // full-screen sheet has to drop `fullscreen` and hand focus back to the
  // trigger; collapsing the aside does neither. With a single mount there is no
  // longer a call site per presentation to carry that distinction, which is just
  // as well — it was never the mount's fact to know, it is the close's.
  const onClose = () =>
    sheet() ? props.viewport.closeSheet() : props.viewport.toggle();

  return (
    <>
      {/* The handle sits OUTSIDE the construction reveal, on its own gate. It
          rides the same signal so the two arrive and leave together, but keeping
          it out is what lets the frame measure the panel itself — inside, the
          marks would be offset by the handle's own width. A hairline splitter has
          no frame to draw, so a plain reveal is the whole of what it needs.

          Gated on the aside specifically: there is nothing to drag when the
          region is covering the screen.

          `divider="hover"` because the panel already brackets itself: at rest the
          frame's left rule is the edge, and the splitter only paints when the
          operator reaches for it. */}
      <Reveal when={props.viewport.asideOpen()} class="flex h-full shrink-0">
        <ResizeHandle
          aria-label="Resize viewport panel"
          divider="hover"
          onResize={props.viewport.onResize}
          onResizeEnd={props.viewport.onResizeEnd}
        />
      </Reveal>

      {/* The presentation lives on a wrapper rather than on the reveal's own
          class, and that is not a preference. `cx` joins class strings; it does
          not merge conflicting Tailwind utilities, and the reveal's wrapper is
          already `relative` — so a `fixed` passed in sits beside it in the class
          list and loses to whichever the generated stylesheet emits later. The
          panel stayed in the flex flow and squeezed the transcript into a
          gutter. A wrapper that is either `contents` or `fixed` has nothing to
          conflict with, and `display: contents` keeps the reveal a direct flex
          child of the row in the aside case. */}
      <div class={cx(sheet() ? "fixed inset-0 z-50" : "contents")}>
        <ConstructionReveal
          when={props.viewport.shown()}
          class="h-full shrink-0"
          contentClass="h-full"
        >
          {/* Covering the screen is a dialog and says so; sitting in the row is
            not, and claiming `aria-modal` there would tell a screen reader the
            conversation beside it had gone away.

            `data-view-sheet` marks this as the dialog the room's own Esc binding
            is allowed to close — every *other* portal-rendered dialog handles
            Esc itself, and two handlers on one key closes two things at once. */}
          <div
            role={sheet() ? "dialog" : undefined}
            aria-modal={sheet() ? "true" : undefined}
            aria-labelledby={sheet() ? "view-sheet-title" : undefined}
            data-view-sheet={sheet() ? "" : undefined}
            style={
              sheet() ? undefined : { width: `${props.viewport.liveWidth()}px` }
            }
            /* No fill of its own — the frosted surface is the framed region
               `ConstructionReveal` draws, and a second glass layer here would
               stack with it and paint the transcript out. */
            class={cx(
              "flex h-full min-w-0 flex-col",
              // Covering the screen, it fills the wrapper; in the row, its width
              // is the dragged one and it must not be squeezed to make room.
              sheet() ? "w-full" : "shrink-0",
            )}
          >
            <Show when={sheet()}>
              <header class="flex shrink-0 items-center gap-3 px-4 py-3">
                <Button
                  variant="ghost"
                  size="sm"
                  leading="chevron-left"
                  onClick={props.viewport.closeSheet}
                >
                  Back to chat
                </Button>
                {/* Named after the surface being worked in, not after the one
                    the panel used to only ever hold — a sheet showing the patch
                    that calls itself "View" is a screen reader being told the
                    wrong thing about the whole dialog. */}
                <span id="view-sheet-title">
                  <Text variant="label" tone="bright">
                    {sheetTitle()}
                  </Text>
                </span>
              </header>
            </Show>
            {/* The focusable panel container, and the thing "focus is in the
                panel" means. It has to be here rather than on a surface: it was
                the View's own root while the View was the only occupant, which
                quietly made every panel-scoped binding — full screen, close the
                pane, the digits, Escape — dead whenever the operator was working
                in any other surface. */}
            <div
              ref={props.viewport.panelRef}
              tabindex={-1}
              class="min-h-0 flex-1 outline-none focus-visible:outline-1 focus-visible:outline-bright"
            >
              <ViewportHost
                // The gate requires `shown()`, which requires a layout — the
                // fallback is for the frame the reveal keeps around on the way out.
                layout={props.viewport.state().layout ?? emptyLayout()}
                ctx={{
                  viewport: props.viewport,
                  onClose,
                  onToggleFullscreen: toggleFullscreen,
                }}
              />
            </div>
          </div>
        </ConstructionReveal>
      </div>
    </>
  );
}
