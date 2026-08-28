import { createMemo, createSignal, Show, type JSX } from "solid-js";
import { MetaAction, Text } from "~/ui";
import type { PlanItem } from "~/lib/stream";
import type { ContextUsage, RunCounters, TokenUsage } from "../model";
import { ContextMeter } from "./ContextMeter";
import { ConversationCompactionToggle } from "./ConversationCompactionToggle";
import { ConversationGrants } from "./ConversationGrants";
import { MetaSep } from "./MetaSep";
import { planSummary, PlanRows } from "./PlanRows";

/** How full the context window must be before the CTX readout appears. Below half a
 *  window there is nothing to act on — no fold is near, no turn is at risk — so the
 *  gauge is a number on screen that asks to be read and then says "fine". It surfaces
 *  well before the backend's own `warn` (75%) and long before auto-compaction fires,
 *  so the operator still sees it climb rather than meeting it already amber. */
const CTX_VISIBLE_AT = 0.5;

/** The conversation's live state, in one quiet line **under the composer**: what the
 *  stream is doing, how much work the last run did, how full the context window is,
 *  how far the agent's plan has got, which tools it may call without asking again,
 *  and the thread's auto-compaction setting.
 *
 *  Three moves got it here. It began as a cluster in the page header plus two stacked
 *  panels; it became one horizontal band above the transcript; and it is now a line of
 *  text below the input. Each step answered the same complaint — every readout was
 *  individually small enough to dismiss and collectively loud enough to bury the thing
 *  it sat next to. Below the composer it is where the eye already is after typing, and
 *  set as `micro` mono in `dim` it reads as texture until the operator wants it.
 *
 *  That framing is also why the three interactive segments are `MetaAction`s rather
 *  than a toggle, a chip run and a disclosure button: this is a readout, and a control
 *  parked inside one is chrome. They are the same type as the values beside them and
 *  only the hover says they act.
 *
 *  Everything quiet stays absent — the meter below its threshold, the plan with no
 *  tasks, the grants with none, the counters before the first run reports any.
 *
 *  Presentation only — every value is the backend's, rendered, never derived here. */
export function ConversationStatusStrip(props: {
  conversationId: () => string | null;
  /** Live transport state, straight from the run stream. */
  streaming: () => boolean;
  reattaching: () => boolean;
  detached: () => boolean;
  /** The backend-derived context-window state, and the last run's token counts. */
  usage: () => ContextUsage | null | undefined;
  tokenUsage: () => TokenUsage | null | undefined;
  /** The last run's step / tool-call counters (`run.metrics`). */
  counters: () => RunCounters | null | undefined;
  /** The agent's task list for this thread (backend-owned, read-only). */
  plan: () => PlanItem[];
  /** Ticks when a grant may have changed, so the chips refetch. */
  grantsRevalidate: () => unknown;
}): JSX.Element {
  const [planOpen, setPlanOpen] = createSignal(false);
  const summary = createMemo(() => planSummary(props.plan()));
  const meter = () => {
    const u = props.usage();
    return u && u.fraction >= CTX_VISIBLE_AT ? u : undefined;
  };
  // A fresh, unsaved composer has no thread to report on and no stream running — a
  // line reading only "Idle" would be the exact clutter this replaced.
  const shown = () =>
    props.conversationId() !== null || props.streaming() || props.detached();

  const transport = () =>
    props.detached()
      ? "Disconnected"
      : props.reattaching()
        ? "Resyncing"
        : props.streaming()
          ? "Streaming"
          : "Idle";

  return (
    <Show when={shown()}>
      <div class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 px-2 pt-1.5">
        {/* Transport state leads, and it is the one segment that is always present —
            it is what the rest of the line is qualifying. Toned, not flagged: a
            `StatusFlag`'s dot and pulse are a badge, and a badge at the head of a run
            of text is the chrome this line dropped. */}
        <Text
          variant="micro"
          tone={props.detached() ? "alert" : props.streaming() ? "info" : "dim"}
        >
          {transport()}
        </Text>

        <Show when={props.counters()}>
          {(c) => (
            <>
              <MetaSep />
              <Text variant="micro" tone="dim" class="tabular-nums">
                {c().steps} {c().steps === 1 ? "step" : "steps"} ·{" "}
                {c().toolCalls}{" "}
                {c().toolCalls === 1 ? "tool call" : "tool calls"}
              </Text>
            </>
          )}
        </Show>

        <Show when={meter()}>
          {(usage) => (
            <>
              <MetaSep />
              <ContextMeter usage={usage()} tokenUsage={props.tokenUsage()} />
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
