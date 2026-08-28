import { createMemo, createSignal, Show, type JSX } from "solid-js";
import { Icon, StatusFlag, Text } from "~/ui";
import type { PlanItem } from "~/lib/stream";
import type { ContextUsage, TokenUsage } from "../model";
import { ContextMeter } from "./ContextMeter";
import { ConversationCompactionToggle } from "./ConversationCompactionToggle";
import { ConversationGrants } from "./ConversationGrants";
import { planSummary, PlanRows } from "./PlanRows";

/** How full the context window must be before the CTX meter appears. Below half a
 *  window there is nothing to act on — no fold is near, no turn is at risk — so the
 *  gauge is a number on screen that asks to be read and then says "fine". It surfaces
 *  well before the backend's own `warn` (75%) and long before auto-compaction fires,
 *  so the operator still sees it fill rather than meeting it already amber. */
const CTX_VISIBLE_AT = 0.5;

/** The conversation's live status, in one horizontal band between the header and the
 *  transcript: what the stream is doing, how full the context window is, the thread's
 *  auto-compaction switch, how far the agent's plan has got, and which tools it may
 *  call without asking again.
 *
 *  These readouts were a cluster in the page header plus two stacked panels below it.
 *  They are one band because they answer one question — *what is this conversation
 *  doing right now* — and because each was individually small enough to be dismissed
 *  and collectively loud enough to bury the title. Everything that is quiet stays
 *  absent: the meter below its threshold, the plan with no tasks, the grants with none.
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
  // band reading only "Idle" would be the exact clutter this replaced.
  const shown = () =>
    props.conversationId() !== null || props.streaming() || props.detached();

  return (
    <Show when={shown()}>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 py-1.5">
        <StatusFlag
          status={
            props.detached() ? "alert" : props.streaming() ? "info" : "idle"
          }
          dot={props.streaming() || props.detached()}
          pulse={props.streaming() && !props.detached()}
        >
          {props.detached()
            ? "Disconnected"
            : props.reattaching()
              ? "Resyncing"
              : props.streaming()
                ? "Streaming"
                : "Idle"}
        </StatusFlag>

        <Show when={meter()}>
          {(usage) => (
            <ContextMeter usage={usage()} tokenUsage={props.tokenUsage()} />
          )}
        </Show>

        {/* The plan's headline, with the rows themselves one click away. The count
            and the ACTIVE flag answer "how far along" on their own; the task text
            is what the operator opens when the answer is "not far". */}
        <Show when={props.plan().length > 0}>
          <button
            type="button"
            class="flex items-center gap-2"
            aria-expanded={planOpen()}
            aria-label={planOpen() ? "Hide the plan" : "Show the plan"}
            onClick={() => setPlanOpen((v) => !v)}
          >
            <Icon
              name={planOpen() ? "chevron-up" : "chevron-down"}
              size={12}
              class="text-dim"
            />
            <Text variant="label" tone="dim">
              Plan
            </Text>
            {/* Tabular figures line up as the count changes mid-turn. */}
            <Text variant="label" tone="bright" class="tabular-nums">
              {summary().done}/{summary().total}
            </Text>
            <Show when={summary().active}>
              {/* Info blue, not warn amber: the running task is live data — the same
                  meaning STREAMING carries beside it. */}
              <StatusFlag status="info" dot pulse>
                Active
              </StatusFlag>
            </Show>
          </button>
        </Show>

        <ConversationGrants
          conversationId={props.conversationId}
          revalidate={props.grantsRevalidate}
        />

        <span class="ml-auto flex items-center gap-2">
          <ConversationCompactionToggle conversationId={props.conversationId} />
        </span>
      </div>
      <Show when={planOpen()}>
        <PlanRows items={props.plan} />
      </Show>
    </Show>
  );
}
