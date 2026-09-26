import { type JSX } from "solid-js";
import { ConstructionReveal } from "./ConstructionReveal";
import { Popover, type PopoverApi } from "./Popover";

export interface RevealPopoverProps {
  /** The clickable trigger; receives the open state + setters, as `Popover`'s does. */
  trigger: (api: PopoverApi) => JSX.Element;
  /** Horizontal alignment of the panel against the trigger. Default left. */
  align?: "left" | "right";
  /** The panel's width (and any other sizing) — `w-88`, say. Layout only: the surface
   *  is the reveal's, and nothing here should restyle it. */
  panelClass?: string;
  /** Laid out as a column with a `gap-3` rhythm inside the framed region. Receives
   *  `close`, for content that dismisses the panel on an act. */
  children: (api: { close: () => void }) => JSX.Element;
}

/** **A popover that arrives as a framed, frosted region** — the View panel's own
 *  container, opened from a small trigger. The context bar's breakdown and the
 *  conversation's stats panel are the two consumers, and they are one shape: a click
 *  on a glance-sized readout opening onto the detail behind it.
 *
 *  Three pieces, and the reason each is here rather than at the call site:
 *
 *  - **`Popover bare`.** The reveal brings its own container, so the popover's card
 *    around it would be the box-in-a-box the frame exists to avoid, with its shadow
 *    sitting on the glass.
 *  - **`ConstructionReveal when`**, with a constant `when`: the frame draws itself
 *    before it fills, so the detail arrives as a place made for it. The popover already
 *    owns the open state and unmounts the panel on close, so this only ever plays its
 *    launch.
 *  - **The padding on a wrapper INSIDE the reveal**, not on its `contentClass`. That
 *    element already carries the `p-1.5` that keeps the content within the framed box,
 *    and a second `p-*` on the same node is a Tailwind conflict resolved by stylesheet
 *    order rather than by intent — which is exactly the kind of thing two hand-copied
 *    call sites drift apart on. */
export function RevealPopover(props: RevealPopoverProps): JSX.Element {
  return (
    <Popover
      align={props.align}
      bare
      panelClass={props.panelClass}
      trigger={props.trigger}
      panel={(api) => (
        <ConstructionReveal when>
          <div class="flex flex-col gap-3 px-4 py-3.5">
            {props.children(api)}
          </div>
        </ConstructionReveal>
      )}
    />
  );
}
