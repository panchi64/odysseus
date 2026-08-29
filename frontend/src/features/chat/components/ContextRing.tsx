import { Show, type JSX } from "solid-js";
import { pct } from "~/lib/format";
import { ProgressRing, Tooltip } from "~/ui";
import type { ContextUsage } from "../model";

export interface ContextRingProps {
  /** The backend-derived context-window state, or null when the window is unknown —
   *  the provider reports none and the operator has set none. */
  usage: ContextUsage | null | undefined;
}

const tokens = (n: number) => n.toLocaleString("en-US");

/** The backend's severity, as a ring tone.
 *
 *  `nominal` deliberately does **not** become the nominal green. A gauge at rest has
 *  no verdict to deliver — the window is filling, which is what windows do — and a
 *  green ring spends attention saying so. It also devalues the colour that matters:
 *  if the ring is always coloured, a colour change is no longer a signal, and the
 *  operator has to *read* the ring to learn anything from it. Grey until 75%, then
 *  amber, then red, means the only time it catches the eye is the time it should.
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
 *  Present at every fullness, and **grey for almost all of it**. The text readout it
 *  replaced only appeared past half a window, because a percentage that says "fine" is
 *  a thing on screen asking to be read and then dismissed. A ring can do better than
 *  appearing and disappearing: it is answered by its own shape at a glance, so it can
 *  sit there permanently as long as it stays quiet while it has nothing to say. That
 *  is what the toning is for — dim until the backend's own `warn`, then amber, then
 *  red. Colour is held in reserve so that colour *means* something; a ring that were
 *  always green would have to be read to be understood, which is the one thing a gauge
 *  should never require. Severity and its thresholds stay the backend's.
 *
 *  The exact figures are one hover away rather than on screen: nobody reads
 *  `142,000 / 200,000` as a fraction faster than they read the arc. */
export function ContextRing(props: ContextRingProps): JSX.Element {
  return (
    <Show when={props.usage} fallback={<UnknownWindow />}>
      {(usage) => {
        const percent = () => usage().fraction * 100;
        return (
          <Tooltip
            label={`Context window ${pct(percent())} full — ${tokens(usage().used)} of ${tokens(usage().window)} tokens`}
            side="top"
            delay={80}
          >
            <ProgressRing
              value={percent()}
              tone={RING_TONE[usage().level]}
              size={18}
              thickness={2}
              label={`Context window ${pct(percent())} full`}
            />
          </Tooltip>
        );
      }}
    </Show>
  );
}

/** The gauge with nothing to measure against: the endpoint reports no context window
 *  and none was configured.
 *
 *  **It renders, rather than disappearing.** Absent is how this component used to
 *  handle it, and that was the wrong lesson from the absent-not-zero rule the readout
 *  line follows: omitting a *statistic* nobody reported says "not measured", but
 *  omitting a *gauge* says "no gauge here", and the operator concludes the feature is
 *  broken instead of unconfigured. The only person who can fix it is the one who can't
 *  see anything is wrong.
 *
 *  Empty and in alert, because both halves are true: nothing is known to be filled,
 *  and something needs attention. It reads as a warning rather than as 0% precisely
 *  because of the colour — an empty nominal ring would be a claim that the window is
 *  wide open, which is the one thing we can't say. Sending is blocked in this state
 *  anyway (the backend refuses the turn), so this is the visible half of a stop the
 *  operator would otherwise only meet on pressing SEND. */
function UnknownWindow(): JSX.Element {
  return (
    <Tooltip
      label="No context window for this model — the endpoint doesn't report one, so the conversation can't be kept inside it. Set one under settings › models › advanced."
      side="top"
      delay={80}
    >
      <ProgressRing
        value={0}
        trackTone="alert"
        size={18}
        thickness={2}
        label="Context window unknown"
      />
    </Tooltip>
  );
}
