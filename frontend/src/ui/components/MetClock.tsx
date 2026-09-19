import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone, type TextVariant } from "../primitives/Text";
import { met, parseInstant } from "~/lib/format";
import { useNow } from "~/lib/useNow";

export interface MetClockProps {
  /** ISO-8601 instant the thing started, from the backend. When absent the clock
   *  reads `--:--:--` rather than zero: "not started" and "started one second ago"
   *  are different facts and must not render the same. */
  startedAt?: string | null;
  /** Freeze at a fixed elapsed instead of ticking — for a run that has ended.
   *  ISO-8601; ignored without `startedAt`. */
  endedAt?: string | null;
  /** `meta` (default) beside other machine state, `plate` inside a console group's
   *  header band where it sits next to engraved legends. */
  variant?: Extract<TextVariant, "meta" | "plate" | "micro">;
  tone?: TextTone;
  /** Prefix the `T+`. On by default — it is what names the figure as elapsed
   *  rather than as a time of day. */
  prefix?: boolean;
  class?: string;
}

const PLACEHOLDER = "--:--:--";

/** Mission elapsed time (§10.16): `T+ 00:14:22`, ticking once a second.
 *
 *  **It is a formatter over a backend timestamp and nothing else.** The frontend is
 *  given `created_at`/`started_at` and renders the difference; it never decides when
 *  anything began, and it holds no start time of its own.
 *
 *  Squarely in the machine register (§8) — mono, no transition, hard cuts between
 *  values. The tick comes from the shared `useNow`, so every clock on screen advances
 *  on the same frame instead of drifting apart.
 *
 *  A finished run passes `endedAt` and stops: a run clock that kept counting after the
 *  run ended would be reporting the age of a record as though it were work in progress.
 */
export function MetClock(props: MetClockProps): JSX.Element {
  const [local] = splitProps(props, [
    "startedAt",
    "endedAt",
    "variant",
    "tone",
    "prefix",
    "class",
  ]);

  // Subscribed unconditionally: a hook call behind a branch would unsubscribe and
  // re-subscribe as a run ends, and the ref-counted ticker would be torn down and
  // rebuilt under every other clock on the screen.
  const now = useNow();

  // `parseInstant`, never `Date.parse`: the backend serializes some timestamps with no
  // zone designator, and the bare parse reads those as local time — which on any host
  // west of Greenwich puts a just-started run in the future and pins its clock at zero.
  const started = (): number | null => {
    if (!local.startedAt) return null;
    const t = parseInstant(local.startedAt);
    return Number.isNaN(t) ? null : t;
  };

  const elapsed = (): string => {
    const from = started();
    if (from === null) return PLACEHOLDER;
    const ended = local.endedAt ? parseInstant(local.endedAt) : NaN;
    return met((Number.isNaN(ended) ? now() : ended) - from);
  };

  return (
    <Text
      variant={local.variant ?? "meta"}
      tone={local.tone ?? "dim"}
      class={cx("tabular-nums", local.class)}
    >
      {local.prefix === false ? elapsed() : `T+ ${elapsed()}`}
    </Text>
  );
}
