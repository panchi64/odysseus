import { Show, type JSX } from "solid-js";
import { Frames, ProgressRing, StatusDot, Text, cx } from "~/ui";
import { duration, parseInstant } from "~/lib/format";
import { isLive, type Subagent, type SubagentStatus } from "../data";
import { SURFACE_CARD } from "./surfaceChrome";

/** How a sub-agent's state reads at a glance.
 *
 *  `blocked` is the only one that is a *request*: the sub-agent has stopped and is
 *  waiting on the operator, who does not otherwise know it. Everything else is a report
 *  about work — in progress, finished, or not finished — so the warn tone is spent
 *  there and nowhere else.
 *
 *  `cancelled` is not an error and is not a success. It reads dim: nothing went wrong,
 *  and nothing came of it either. */
const TONE: Record<SubagentStatus, "dim" | "bright" | "warn" | "alert"> = {
  running: "bright",
  blocked: "warn",
  done: "bright",
  failed: "alert",
  cancelled: "dim",
};

const LABEL: Record<SubagentStatus, string> = {
  running: "working",
  blocked: "waiting for you",
  done: "done",
  failed: "failed",
  cancelled: "stopped",
};

/** How full its context window is, 0–100, or null when nothing has measured it yet.
 *
 *  Null rather than zero for the unmeasured case: an empty ring and a ring nobody has
 *  filled in draw identically, and only one of them means the sub-agent has done
 *  nothing. A sub-agent that has not made a model request yet simply has no gauge. */
function fullness(subagent: Subagent): number | null {
  const { contextUsed: used, contextWindow: window } = subagent;
  if (used === null || window === null || window <= 0) return null;
  return Math.min(100, Math.round((used / window) * 100));
}

/** Grey until it is worth looking at, then amber, then red — the composer's own gauge
 *  reads the operator's thresholds from the backend, and a sub-agent's card is a glance
 *  rather than a setting, so it takes fixed ones. */
function ringTone(value: number): "dim" | "warn" | "alert" {
  if (value >= 90) return "alert";
  return value >= 75 ? "warn" : "dim";
}

/** How long it ran, in the coarsest unit that is still true.
 *
 *  That is `duration()`'s contract verbatim, so it is `duration()` — this used to
 *  hand-roll the first two of its branches and stop, which meant a sub-agent that ran
 *  three minutes read `184.0s` where every other elapsed figure in the product read
 *  `3m4s`. */
function took(subagent: Subagent): string | null {
  if (subagent.endedAt === null) return null;
  const ms = parseInstant(subagent.endedAt) - parseInstant(subagent.startedAt);
  if (!Number.isFinite(ms) || ms < 0) return null;
  return duration(ms);
}

/**
 * One sub-agent, as a card.
 *
 * Three things, and they are the three the operator asked for: **who** it is, **how
 * much room it has left**, and **what it is doing right now**. Everything else about it
 * — the whole transcript — is one click away and deliberately not here, because a card
 * that tried to show the work would be a worse transcript and a much worse card.
 *
 * **One component, one variant prop.** A live card, a finished one and a failed one
 * differ in tone and in which line they show, and nothing else. Three components that
 * looked alike on the day they were written would not still look alike a month later.
 *
 * The context ring is here for the same reason the composer carries its context bar: a
 * sub-agent nobody is watching can fill its window and stop, and a number in a row of
 * numbers is something you read, where an arc closing on itself is something you notice.
 */
export function SubagentCard(props: {
  subagent: Subagent;
  /** Open this sub-agent's own view. The card is a way in, not a thing that unfolds —
   *  see `SubagentsSurface` for why the transcript stopped living underneath it. */
  onOpen: () => void;
}): JSX.Element {
  // While it runs this is its latest answer rather than a report — a current best. Once
  // it has finished it is what it actually handed back, and a failure replaces it with
  // why, because that is the thing the operator opened the panel for.
  const line = (): string => {
    const s = props.subagent;
    if (s.status === "failed") return s.error ?? "failed";
    return s.summary ?? (isLive(s) ? "working…" : "reported nothing");
  };

  return (
    <button
      type="button"
      onClick={() => props.onOpen()}
      /* The surface card its neighbours sit on, so a sub-agent reads as a sibling of a
         command or a topic rather than as a second, outlined kind of thing. */
      class={cx(
        SURFACE_CARD,
        "flex w-full flex-col gap-1 px-2 py-1.5 text-left hover:bg-raised",
      )}
    >
      <div class="flex min-w-0 items-center gap-2">
        <Show
          when={props.subagent.status !== "running"}
          fallback={<Frames class="shrink-0 text-info" />}
        >
          <StatusDot
            class="shrink-0"
            status={
              props.subagent.status === "failed"
                ? "alert"
                : props.subagent.status === "blocked"
                  ? "warn"
                  : "nominal"
            }
          />
        </Show>
        {/* The handle, not the roster name: the launching agent named this one for the
            job it is doing, and `explorer` three times over identifies nothing. The
            roster name is on the meta line below, where it belongs — it says what kind
            of sub-agent this is, which is a detail about it rather than its identity.

            Capped and truncated, which the roster name never needed to be: a handle is
            whatever the launching model typed and nothing holds it to a few words, so an
            unbounded one would overflow the row and squeeze the task beside it away. The
            cap is the same share `ProcessRow` gives its label. */}
        <Text variant="label" tone="bright" class="max-w-2/5 shrink-0 truncate">
          {props.subagent.handle}
        </Text>
        <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
          {props.subagent.task}
        </Text>
        {/* `!== null`, not the value itself: a sub-agent that has barely started rounds
            to 0, and 0 is falsy — a truthiness test would hide the ring for exactly the
            cards that have just appeared and are the ones being watched. */}
        <Show when={fullness(props.subagent) !== null}>
          <ProgressRing
            class="shrink-0"
            value={fullness(props.subagent) ?? 0}
            tone={ringTone(fullness(props.subagent) ?? 0)}
            label={`context ${fullness(props.subagent) ?? 0}% full`}
          />
        </Show>
      </div>
      {/* The summary takes its own line in a narrow pane and joins the row once there is
          room: it is what the sub-agent actually said, and at 320px a one-line slot
          beside the name and state would truncate it to a word. */}
      <div class="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
        <Text variant="micro" tone="dim" class="shrink-0">
          {props.subagent.name}
        </Text>
        <Text
          variant="micro"
          tone={TONE[props.subagent.status]}
          class="shrink-0"
        >
          · {LABEL[props.subagent.status]}
        </Text>
        <Show when={took(props.subagent)}>
          {/* Not named `duration` — that is the shared formatter `took` now calls,
              and shadowing it here is how the next edit reaches for the wrong one. */}
          {(ran) => (
            <Text variant="micro" tone="dim" class="shrink-0">
              · {ran()}
            </Text>
          )}
        </Show>
        <Text
          variant="micro"
          tone="dim"
          class="line-clamp-2 min-w-0 basis-full break-words @sm:flex-1 @sm:basis-0"
        >
          {line()}
        </Text>
      </div>
    </button>
  );
}
