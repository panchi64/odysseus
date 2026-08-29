import { type JSX } from "solid-js";
import { pct } from "~/lib/format";
import { ConstructionReveal, Popover, ProgressRing } from "~/ui";
import type { ContextUsage } from "../model";
import { ContextBreakdown } from "./ContextBreakdown";

export interface ContextRingProps {
  /** The backend-derived context-window state. Non-null by construction: the caller
   *  mounts the ring only once a run has reported one, because a gauge with nothing
   *  to measure has nothing to say. The window being genuinely unknown is the send
   *  gate's to report, not this one's. */
  usage: ContextUsage;
}

/** The backend's severity, as a tone.
 *
 *  `nominal` deliberately does **not** become the nominal green. A gauge at rest has
 *  no verdict to deliver — the window is filling, which is what windows do — and a
 *  green ring spends attention saying so. It also devalues the colour that matters:
 *  if the ring is always coloured, a colour change is no longer a signal, and the
 *  operator has to *read* the ring to learn anything from it. Grey until the operator's
 *  warn boundary, then amber, then red, means the only time it catches the eye is the
 *  time it should.
 *
 *  The thresholds themselves stay the backend's — this maps a level, it doesn't
 *  decide one. */
const RING_TONE = {
  nominal: "dim",
  warn: "warn",
  alert: "alert",
} as const;

/** How full the model's context window is, as a dial in the composer's action row.
 *
 *  It sits **beside SEND rather than in the readout line below**, and that is the
 *  whole of why it is a ring and not the `Ctx 62%` text it replaced. Everything in
 *  the line under the composer is a *tally* — what the thread has spent, counting up
 *  from zero with no ceiling in sight. This is the one figure with a ceiling, and the
 *  ceiling is the point: the operator is not tracking how many tokens the window
 *  holds, they are watching for the moment it runs out. A number in a row of numbers
 *  makes that something you read; an arc closing on itself makes it something you
 *  notice without reading, which is what a limit you are approaching should be.
 *
 *  Present at every fullness, and **grey for almost all of it**. A ring is answered by
 *  its own shape at a glance, so it can sit there permanently as long as it stays quiet
 *  while it has nothing to say. Colour is held in reserve so that colour *means*
 *  something.
 *
 *  **Click for the breakdown** (`ContextBreakdown`). The exact figures were a tooltip,
 *  which is the right weight for one number and the wrong weight for a dozen: a tooltip
 *  can't be read at the operator's pace, can't be pointed at, and disappears the moment
 *  they move to act on it. What the ring answers at a glance is *how full*; the question
 *  it provokes is *full of what* — and that one is worth a click, because the answers
 *  lead to different actions. */
export function ContextRing(props: ContextRingProps): JSX.Element {
  return (
    <Popover
      align="right"
      bare
      panelClass="w-88"
      trigger={({ open, setOpen }) => (
        <button
          type="button"
          class="flex cursor-pointer items-center rounded-ctl"
          aria-expanded={open()}
          aria-label={`Context window ${pct(props.usage.fraction * 100)} full`}
          onClick={() => setOpen(!open())}
        >
          <ProgressRing
            value={props.usage.fraction * 100}
            tone={RING_TONE[props.usage.level]}
            size={18}
            thickness={2}
          />
        </button>
      )}
      panel={() => (
        // The View panel's own container, reused rather than restyled: the frame
        // draws itself before it fills, and the glass inside it is the framed region
        // — so the breakdown arrives as a place that was made for it. `when` is a
        // constant because the Popover already owns the open state and unmounts the
        // panel on close; this only ever plays its launch.
        <ConstructionReveal when>
          {/* The padding goes on a wrapper INSIDE the reveal, not on its
              `contentClass`: that element already carries the `p-1.5` that keeps the
              content within the framed box, and a second `p-*` on the same node is a
              Tailwind conflict resolved by stylesheet order rather than by intent. */}
          <div class="flex flex-col gap-3 px-4 py-3.5">
            <ContextBreakdown usage={props.usage} />
          </div>
        </ConstructionReveal>
      )}
    />
  );
}
