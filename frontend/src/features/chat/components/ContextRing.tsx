import type { JSX } from "solid-js";
import { pct } from "~/lib/format";
import { ProgressRing, Tooltip } from "~/ui";
import type { ContextUsage } from "../model";

export interface ContextRingProps {
  /** The backend-derived context-window state. The ring only renders it. */
  usage: ContextUsage;
}

const tokens = (n: number) => n.toLocaleString("en-US");

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
 *  Present at every fullness. The text readout only appeared past half a window,
 *  because a percentage that says "fine" is a thing on screen asking to be read and
 *  then dismissed — but a ring at a quarter is answered by its own shape at a glance,
 *  and a gauge that materializes partway through is a worse surprise than one that
 *  was quietly there all along. Severity still comes from the backend's own level, so
 *  it goes amber and red on the same thresholds every other surface uses.
 *
 *  The exact figures are one hover away rather than on screen: nobody reads
 *  `142,000 / 200,000` as a fraction faster than they read the arc. */
export function ContextRing(props: ContextRingProps): JSX.Element {
  const percent = () => props.usage.fraction * 100;
  return (
    <Tooltip
      label={`Context window ${pct(percent())} full — ${tokens(props.usage.used)} of ${tokens(props.usage.window)} tokens`}
      side="top"
      delay={80}
    >
      <ProgressRing
        value={percent()}
        tone={props.usage.level}
        size={18}
        thickness={2}
        label={`Context window ${pct(percent())} full`}
      />
    </Tooltip>
  );
}
