import { Show, type JSX } from "solid-js";
import { Portal } from "solid-js/web";
import { Button, ConstructionReveal, ResizeHandle, Reveal, Text } from "~/ui";
import type { ChatViewport } from "../useChatViewport";
import { BrowserPanel } from "./BrowserPanel";
import { ViewportPanel } from "./ViewportPanel";

export interface ChatViewportMountsProps {
  viewport: ChatViewport;
  /** The stream path of the thread's live agent browser, or null. */
  browserStream: () => string | null;
  /** The socket says the session is gone — the only signal a reap can produce. */
  onBrowserEnded: () => void;
}

/**
 * The two places the viewport can be, and the one panel that goes in either.
 *
 * Above `lg` it is a resizable aside beside the conversation; below `lg`, or in fullscreen
 * at any width, the same panel renders in a full-screen sheet. The panel's JSX is
 * therefore defined once and placed conditionally — never both at once, since only one
 * `Show` branch mounts at a time, so the panel's own state never runs twice.
 *
 * `onClose` is passed per mount site: the aside's own Collapse just toggles the panel, but
 * the sheet's (routed through the same `ViewActionRow`) must also reset `fullscreen` and
 * return focus to the trigger — `closeSheet` does both, `toggle` does neither.
 *
 * **A live browser takes the slot.** A browser is a place the agent *is*, not an artifact
 * it produced, so it gets none of the View's version chrome — and it is transient, so the
 * versioned View comes straight back when the session ends rather than the operator having
 * to switch back to it.
 *
 * **Resolve and dissolve at full width — an *animation*, not a transition.** The
 * difference is mechanism rather than taste: a transition needs a previous computed value,
 * and a region that mounts the instant it is opened has none, so it would appear at its
 * end state. That is the whole reason the sheet always faded correctly and the aside never
 * did. `ConstructionReveal` rather than `Reveal` because the View is a region the operator
 * deliberately opens, so it is *built* — a `+` splits, travels the top edge, drops down the
 * sides, and the glass resolves inside the frame it just described.
 */
export function ChatViewportMounts(
  props: ChatViewportMountsProps,
): JSX.Element {
  const toggleFullscreen = () =>
    props.viewport.patch({ fullscreen: !props.viewport.state().fullscreen });

  const renderViewportPanel = (onClose: () => void) => (
    <ViewportPanel
      items={props.viewport.items()}
      selectedKey={props.viewport.state().pinnedKey}
      onSelect={props.viewport.selectView}
      activeTab={props.viewport.state().activeTab}
      onSelectTab={props.viewport.requestTab}
      fontStep={props.viewport.state().fontStep}
      onFontStep={(step) => props.viewport.patch({ fontStep: step })}
      softWrap={props.viewport.state().softWrap}
      onToggleWrap={() =>
        props.viewport.patch({ softWrap: !props.viewport.state().softWrap })
      }
      fullscreen={props.viewport.state().fullscreen}
      onToggleFullscreen={toggleFullscreen}
      onClose={onClose}
      onKeeper={props.viewport.toggleKeeper}
      panelRef={props.viewport.panelRef}
    />
  );

  const renderPanel = (onClose: () => void) => (
    <Show when={props.browserStream()} fallback={renderViewportPanel(onClose)}>
      {(path) => (
        <BrowserPanel
          streamPath={path()}
          onEnded={props.onBrowserEnded}
          fullscreen={props.viewport.state().fullscreen}
          onToggleFullscreen={toggleFullscreen}
          onClose={onClose}
          panelRef={props.viewport.panelRef}
        />
      )}
    </Show>
  );

  return (
    <>
      {/* The breakpoint lives on a wrapper so the `lg:contents` leaves the reveal
          as a direct flex child of the row. */}
      <div class="hidden lg:contents">
        {/* The handle sits OUTSIDE the construction reveal, on its own gate. It
            rides the same signal so the two arrive and leave together, but
            keeping it out is what lets the frame measure the panel itself —
            inside, the marks would be offset by the handle's own width.
            A hairline splitter has no frame to draw, so a plain reveal is the
            whole of what it needs.

            `divider="hover"` because the panel already brackets itself: at rest
            the frame's left rule is the edge, and the splitter only paints when
            the operator reaches for it. */}
        <Reveal when={props.viewport.asideOpen()} class="flex h-full shrink-0">
          <ResizeHandle
            aria-label="Resize viewport panel"
            divider="hover"
            onResize={props.viewport.onResize}
            onResizeEnd={props.viewport.onResizeEnd}
          />
        </Reveal>
        <ConstructionReveal
          when={props.viewport.asideOpen()}
          class="h-full shrink-0"
          contentClass="h-full"
        >
          <aside
            class="min-w-0 shrink-0"
            style={{ width: `${props.viewport.liveWidth()}px` }}
          >
            {renderPanel(props.viewport.toggle)}
          </aside>
        </ConstructionReveal>
      </div>

      {/* The sheet is an overlay, so it has no space to give back — it is built
          and taken apart in place, on the same choreography as the aside.

          This is the one place the backdrop blur genuinely earns itself: the
          sheet sits directly over the transcript, so there is real content
          behind it to frost. The dialog carries the glass rather than an opaque
          `bg-bg`, which is what lets the conversation stay faintly legible
          underneath — the panel inside it is on the same surface and needs no
          fill of its own. */}
      <Portal>
        <ConstructionReveal
          when={props.viewport.sheetOpen()}
          class="fixed inset-0 z-50"
          contentClass="h-full"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="view-sheet-title"
            data-view-sheet
            /* No fill of its own — the frosted surface is the framed region
               `ConstructionReveal` draws, and a second glass layer here would
               stack with it and paint the transcript out. */
            class="flex h-full flex-col"
          >
            <header class="flex items-center gap-3 px-4 py-3">
              <Button
                variant="ghost"
                size="sm"
                leading="chevron-left"
                onClick={props.viewport.closeSheet}
              >
                Back to chat
              </Button>
              <span id="view-sheet-title">
                <Text variant="label" tone="bright">
                  View
                </Text>
              </span>
            </header>
            <div class="min-h-0 flex-1">
              {renderPanel(props.viewport.closeSheet)}
            </div>
          </div>
        </ConstructionReveal>
      </Portal>
    </>
  );
}
