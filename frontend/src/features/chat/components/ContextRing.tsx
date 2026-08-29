import { For, Show, type JSX } from "solid-js";
import type { ContextComposition } from "~/lib/stream";
import { compactCount, pct } from "~/lib/format";
import { ConstructionReveal, Popover, ProgressRing, Text } from "~/ui";
import type { ContextUsage } from "../model";

export interface ContextRingProps {
  /** The backend-derived context-window state, or null when the window is unknown —
   *  the provider reports none and the operator has set none. */
  usage: ContextUsage | null | undefined;
}

const tokens = (n: number) => n.toLocaleString("en-US");

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

/** The same severity on the panel's headline figure. It differs from `RING_TONE` in one
 *  place: at rest the ring is `dim` (a gauge with nothing to say should recede) but the
 *  headline is `bright`, because a panel the operator deliberately opened is not
 *  competing for attention — they are already looking at it, and dimming the one number
 *  they opened it to read would be restraint pointed at the wrong thing. */
const HEADLINE_TONE = {
  nominal: "bright",
  warn: "warn",
  alert: "alert",
} as const;

/** The three parts, in the order they are stacked — smallest and most fixed first, so
 *  the bar reads left to right as "what I can't change, then what I can".
 *
 *  **Distinguished by luminance, not by hue.** Three arbitrary colours would be the
 *  obvious way to key a legend, and it is the one thing the palette rule forbids:
 *  colour here means severity and nothing else, so spending three hues on category
 *  labels would leave the amber that matters competing with a purple that doesn't.
 *  Neutral steps carry the same distinction — and they order the parts by weight while
 *  they do it, since the brightest is the one the operator can actually act on. */
const SEGMENTS = [
  { key: "system", label: "System prompt", fill: "bg-dim" },
  { key: "tools", label: "Tools", fill: "bg-text" },
  { key: "messages", label: "Messages", fill: "bg-bright" },
] as const satisfies readonly {
  key: keyof ContextComposition;
  label: string;
  fill: string;
}[];

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
 *  **Click for the breakdown.** The exact figures were a tooltip, which is the right
 *  weight for one number and the wrong weight for four: a tooltip can't be read at the
 *  operator's pace, can't be pointed at, and disappears the moment they move to act on
 *  it. What the ring answers at a glance is *how full*; the question it provokes is
 *  *full of what* — and that one is worth a click, because the answers lead to
 *  different actions (a thread heavy with messages wants compaction, one heavy with
 *  tool schemas wants fewer tools switched on). */
export function ContextRing(props: ContextRingProps): JSX.Element {
  return (
    <Popover
      align="right"
      bare
      panelClass="w-80"
      trigger={({ open, setOpen }) => (
        <button
          type="button"
          class="flex cursor-pointer items-center rounded-ctl"
          aria-expanded={open()}
          aria-label={
            props.usage
              ? `Context window ${pct(props.usage.fraction * 100)} full`
              : "Context window unknown"
          }
          onClick={() => setOpen(!open())}
        >
          <ProgressRing
            value={props.usage ? props.usage.fraction * 100 : 0}
            tone={props.usage ? RING_TONE[props.usage.level] : undefined}
            trackTone={props.usage ? undefined : "alert"}
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
            <Show when={props.usage} fallback={<UnknownWindow />}>
              {(usage) => <Breakdown usage={usage()} />}
            </Show>
          </div>
        </ConstructionReveal>
      )}
    />
  );
}

/** The panel: the headline fraction, the bar, and what fills it. */
function Breakdown(props: { usage: ContextUsage }): JSX.Element {
  const percent = () => props.usage.fraction * 100;
  return (
    <>
      <div class="flex items-baseline justify-between gap-3">
        <div class="flex items-baseline gap-2">
          {/* The hero value: sans and tabular, per the readout rule — a headline figure
              is the interface speaking, not the machine listing. The only thing that
              varies is its tone, and it carries the same severity the ring does, so the
              hue means here exactly what it means out there. */}
          <Text
            variant="readout"
            tone={HEADLINE_TONE[props.usage.level]}
            class="tabular-nums"
          >
            {pct(percent())}
          </Text>
          <Text variant="label" tone="dim">
            of context used
          </Text>
        </div>
        <Text variant="micro" tone="dim">
          ~{compactCount(props.usage.used)} / {compactCount(props.usage.window)}
        </Text>
      </div>

      <Bar usage={props.usage} />

      <Show
        when={props.usage.parts}
        fallback={
          <Text variant="micro" tone="dim">
            The breakdown appears once a turn has run — the tool schemas and
            system prompt aren't in the stored transcript, so they're measured
            as a message is sent.
          </Text>
        }
      >
        {(parts) => (
          <div class="flex flex-col gap-1">
            <For each={SEGMENTS}>
              {(segment) => (
                <div class="flex items-center justify-between gap-3">
                  <div class="flex min-w-0 items-center gap-2">
                    <span
                      class={`size-2 shrink-0 rounded-ctl ${segment.fill}`}
                    />
                    <Text variant="label" tone="default">
                      {segment.label}
                    </Text>
                  </div>
                  <Text variant="micro" tone="dim">
                    ~{compactCount(parts()[segment.key])}
                  </Text>
                </div>
              )}
            </For>
          </div>
        )}
      </Show>

      {/* The one place the exact number lives. Everything above is rounded, because a
          gauge is read for its magnitude — but the operator deciding whether to compact
          wants the real figure, and it costs one dim line to give it to them. */}
      <Text variant="micro" tone="dim">
        {tokens(props.usage.used)} of {tokens(props.usage.window)} tokens
      </Text>
    </>
  );
}

/** The fullness bar, split by what fills it.
 *
 *  Segments are sized against the **window**, not against `used`, so the bar reads as
 *  the window itself: the filled run is the fraction the ring draws, and the track to
 *  its right is the room left. A bar normalised to `used` would show a full-width
 *  three-part strip on a 5%-full thread, which says the opposite of what the ring
 *  beside it says. */
function Bar(props: { usage: ContextUsage }): JSX.Element {
  const share = (tokenCount: number) =>
    `${Math.max(0, Math.min(100, (tokenCount / props.usage.window) * 100))}%`;
  return (
    <div class="flex h-1 w-full overflow-hidden rounded-ctl bg-line">
      <Show
        when={props.usage.parts}
        fallback={
          // No split measured: one undifferentiated run, at the same weight the
          // largest segment would have had. Better than three equal guesses.
          <div
            class="h-full bg-bright"
            style={{ width: share(props.usage.used) }}
          />
        }
      >
        {(parts) => (
          <For each={SEGMENTS}>
            {(segment) => (
              <div
                class={`h-full ${segment.fill}`}
                style={{ width: share(parts()[segment.key]) }}
              />
            )}
          </For>
        )}
      </Show>
    </div>
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
    <>
      <Text variant="label" tone="default">
        No context window for this model
      </Text>
      <Text variant="micro" tone="dim">
        The endpoint doesn't report one, so the conversation can't be kept
        inside it — and sending is blocked until it's known. Set one under
        settings › models › advanced.
      </Text>
    </>
  );
}
