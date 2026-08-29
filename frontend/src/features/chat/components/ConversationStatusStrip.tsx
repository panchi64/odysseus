import { createMemo, createSignal, Show, type JSX } from "solid-js";
import { compactCount, duration, pct } from "~/lib/format";
import { MetaAction, Text, Tooltip } from "~/ui";
import type { PlanItem } from "~/lib/stream";
import type { ConversationStats } from "../model";
import { ConversationCompactionToggle } from "./ConversationCompactionToggle";
import { ConversationGrants } from "./ConversationGrants";
import { MetaSep } from "./MetaSep";
import { planSummary, PlanRows } from "./PlanRows";

const tokens = (n: number) => n.toLocaleString("en-US");

/** One group of the readout: a hoverable explanation over a run of values.
 *
 *  Every segment gets one. The line is deliberately terse — `TTFT avg 20.5s` is four
 *  words the operator has to already know — and the alternative to a tooltip is
 *  either spelling each one out (which is the clutter this line was rebuilt to
 *  escape) or leaving them as jargon that never becomes legible. */
function Segment(props: { hint: string; children: JSX.Element }): JSX.Element {
  return (
    <Tooltip label={props.hint} side="top" delay={200}>
      <Text variant="micro" tone="dim" class="tabular-nums">
        {props.children}
      </Text>
    </Tooltip>
  );
}

/** What the thread has cost, in one quiet line **under the composer**, plus how far the
 *  agent's plan has got, which tools it may call without asking again, and the thread's
 *  auto-compaction setting.
 *
 *  It does **not** report what the stream is doing. It used to lead with a transport
 *  word — Streaming, Idle, Resyncing — and that was the line's worst inch: the
 *  transcript already shows a run in flight, in the place the operator is looking, so
 *  the readout was restating it, and doing so in the brightest tone on the line. A
 *  status that repeats what is visible a few pixels above earns none of the attention
 *  its colour was taking. Only `Disconnected` survives, because a dead stream is the
 *  one state the transcript can't show by animating.
 *
 *  Three moves got it here. It began as a cluster in the page header plus two stacked
 *  panels; it became one horizontal band above the transcript; and it is now a line of
 *  text below the input. Each step answered the same complaint — every readout was
 *  individually small enough to dismiss and collectively loud enough to bury the thing
 *  it sat next to. Below the composer it is where the eye already is after typing, and
 *  set as `micro` mono in `dim` it reads as texture until the operator wants it.
 *
 *  That framing is also why the interactive segments are `MetaAction`s rather than a
 *  toggle, a chip run and a disclosure button: this is a readout, and a control parked
 *  inside one is chrome. They are the same type as the values beside them and only the
 *  hover says they act.
 *
 *  **What the numbers count.** Everything here is cumulative over the *conversation*,
 *  not the last run — the line used to report a single turn and reset to zero at the
 *  start of the next, which meant the one moment an operator wants to know what a long
 *  thread has spent was the moment it went blank. `turns` are the operator's own
 *  exchanges and `steps` the model round-trips inside them, so a ratio between the two
 *  is itself information: 1 turn to 25 steps is a thread doing a lot of tool work per
 *  question.
 *
 *  **Everything unmeasured stays absent** — not zeroed. A `null` from the backend means
 *  nobody reported that figure (an endpoint that sends no cache tokens, turns recorded
 *  before the stopwatch existed), and a `0%` cache hit would read as a broken cache
 *  rather than an unreported one. Same rule as the segments that resolve their own
 *  presence: the meter below its threshold, the plan with no tasks, the grants with none.
 *
 *  Presentation only — every value is the backend's, rendered, never derived here. The
 *  averages and rates arrive already computed for exactly that reason. */
export function ConversationStatusStrip(props: {
  conversationId: () => string | null;
  /** Whether a run is live. Not rendered — the transcript says that far better than
   *  a word here could. It only decides whether a not-yet-saved thread has anything
   *  to show a line for at all. */
  streaming: () => boolean;
  /** The stream gave up reconnecting. The one transport state that still appears
   *  here, because it is not "what's happening" but "nothing is happening any more". */
  detached: () => boolean;
  /** What the thread has cost — cumulative, backend-derived. */
  stats: () => ConversationStats | null | undefined;
  /** The agent's task list for this thread (backend-owned, read-only). */
  plan: () => PlanItem[];
  /** Ticks when a grant may have changed, so the chips refetch. */
  grantsRevalidate: () => unknown;
}): JSX.Element {
  const [planOpen, setPlanOpen] = createSignal(false);
  const summary = createMemo(() => planSummary(props.plan()));
  // A thread that has run at all has counted at least one step. Guarding on the
  // object alone would render a row of zeroes for the beat before the first frame.
  const stats = createMemo(() => {
    const s = props.stats();
    return s && s.steps > 0 ? s : undefined;
  });

  // A fresh, unsaved composer has no thread to report on and no stream running.
  const shown = () =>
    props.conversationId() !== null || props.streaming() || props.detached();

  return (
    <Show when={shown()}>
      {/* Held below `dim` — the floor of the tone ramp — by dimming the row itself.
          A tone token would be a global addition for a single consumer, and this line
          is the one place in the product that wants to sit *under* the quietest thing
          the system otherwise draws. It is a footer of measurements, legible when
          looked at and texture when not; every value in it also has a tooltip, so
          nothing here is the only copy of anything. */}
      <div class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 px-2 pt-1.5 opacity-70">
        {/* No live transport state. "Streaming"/"Idle" restated what the transcript
            already shows — the live rail beside the answer, the composer's own LED
            strip — and did it in `info` blue, so the loudest thing on the line was
            the one word carrying no information the operator didn't have.
            `Disconnected` stays: it is not a phase of normal operation, it is the
            absence of one, and red for a stream that has actually stopped is not
            competing for attention, it is the point. */}
        <Show when={props.detached()}>
          <Text variant="micro" tone="alert">
            Disconnected
          </Text>
        </Show>

        <Show when={stats()}>
          {(s) => (
            <>
              {/* Shape of the work: how many times the operator asked, and how much
                  the model did between asks. Its leading separator is conditional
                  now that nothing reliably precedes it — with the transport state
                  gone, an unconditional one would open the line with a bare rule. */}
              <Show when={props.detached()}>
                <MetaSep />
              </Show>
              <Segment hint="Exchanges you've had, and the model round-trips they took. A high step count per turn means the agent is doing a lot of tool work per question.">
                {s().turns} {s().turns === 1 ? "turn" : "turns"} · {s().steps}{" "}
                {s().steps === 1 ? "step" : "steps"}
                <Show when={s().toolCalls > 0}>
                  {" · "}
                  {s().toolCalls}{" "}
                  {s().toolCalls === 1 ? "tool call" : "tool calls"}
                </Show>
              </Segment>

              {/* Where the time went. The two halves are the whole wait split in
                  one place — a slow thread is either the model or the tools, and
                  which one it is decides what to do about it. */}
              <Show when={s().llmMs !== null || s().toolMs !== null}>
                <MetaSep />
                <Segment hint="Wall-clock spent waiting on the model, and running its tools. Measured here rather than reported by the provider, so it means the same on every endpoint.">
                  <Show when={s().llmMs !== null}>
                    LLM {duration(s().llmMs!)}
                  </Show>
                  <Show when={s().llmMs !== null && s().toolMs}>{" · "}</Show>
                  <Show when={s().toolMs}>
                    Tool calls {duration(s().toolMs!)}
                  </Show>
                </Segment>
              </Show>

              {/* Responsiveness: how long until something appears, and how fast it
                  arrives once it does. Two different complaints about one model. */}
              <Show
                when={s().ttftAvgMs !== null || s().tokensPerSecond !== null}
              >
                <MetaSep />
                <Segment hint="Average wait before the model produces anything (reasoning counts), and its generation speed once it starts.">
                  <Show when={s().ttftAvgMs !== null}>
                    TTFT avg {duration(s().ttftAvgMs!)}
                  </Show>
                  <Show
                    when={
                      s().ttftAvgMs !== null && s().tokensPerSecond !== null
                    }
                  >
                    {" · "}
                  </Show>
                  <Show when={s().tokensPerSecond !== null}>
                    {s().tokensPerSecond!.toFixed(1)} tok/s
                  </Show>
                </Segment>
              </Show>

              {/* Absent, not zero: most OpenAI-compatible and local endpoints never
                  report a cache figure, and "Cache hit 0%" would read as a fault. */}
              <Show when={s().cacheHitRatio !== null}>
                <MetaSep />
                <Segment hint="Share of prompt tokens the provider served from its own cache. Only shown for providers that report it.">
                  Cache hit {pct(s().cacheHitRatio! * 100)}
                </Segment>
              </Show>

              {/* Last, and abbreviated: the magnitude is what's read here — the
                  exact figures are in the tooltip, where a seven-digit number can
                  be looked at rather than scanned past. */}
              <Show when={s().inputTokens !== null}>
                <MetaSep />
                <Segment
                  hint={`${tokens(s().inputTokens!)} tokens in, ${tokens(s().outputTokens ?? 0)} out, across the whole thread. Input counts every turn's replayed history, so it grows far faster than output.`}
                >
                  In {compactCount(s().inputTokens!)}
                  <Show when={s().outputTokens !== null}>
                    {" · out "}
                    {compactCount(s().outputTokens!)}
                  </Show>
                </Segment>
              </Show>
            </>
          )}
        </Show>

        {/* The count and the ACTIVE state answer "how far along" on their own; the
            task text is what the operator opens when the answer is "not far". */}
        <Show when={props.plan().length > 0}>
          <MetaSep />
          <MetaAction
            active={planOpen()}
            aria-expanded={planOpen()}
            aria-label={planOpen() ? "Hide the plan" : "Show the plan"}
            onClick={() => setPlanOpen((v) => !v)}
            class="tabular-nums"
          >
            Plan {summary().done}/{summary().total}
            {/* Info blue, not warn amber: a running task is live data — the same
                meaning STREAMING carries at the head of the line. */}
            <Show when={summary().active}>
              <span class="text-info">· active</span>
            </Show>
          </MetaAction>
        </Show>

        {/* Both of these resolve their own presence from their own resource, so
            each renders its own leading `MetaSep` from inside that check — see the
            note on `MetaSep`. Emitting one here would leave a bar hanging in the
            line for a thread that has no grants. */}
        <ConversationGrants
          conversationId={props.conversationId}
          revalidate={props.grantsRevalidate}
        />
        <ConversationCompactionToggle conversationId={props.conversationId} />
      </div>

      {/* The rows open downward from the segment that discloses them. They sit
          inside the same sticky dock, so opening the plan grows the dock rather
          than scrolling the transcript out from under it. */}
      <Show when={planOpen() && props.plan().length > 0}>
        <div class="pt-2">
          <PlanRows items={props.plan} />
        </div>
      </Show>
    </Show>
  );
}
