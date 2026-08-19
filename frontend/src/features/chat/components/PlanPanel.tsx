import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { cx, Icon, Panel, Row, StatusFlag, Text } from "~/ui";
import type { PlanItem } from "~/lib/stream";

/** Compact window: the readout shows at most this many rows — enough to see
 *  where work is and what comes next without pushing the transcript off screen. */
const WINDOW = 5;

/** Status square (§6.7 list row, §4 semantic color): filled = done (nominal
 *  green) or running (info blue); empty + bordered = not started. Fill vs border
 *  carries the state in shape, so hue is never the only signal (§9). */
const SQUARE: Record<PlanItem["status"], string> = {
  completed: "bg-nominal",
  in_progress: "bg-info",
  pending: "border border-dim",
  cancelled: "border border-line",
  blocked: "border border-alert",
};

const TONE: Record<PlanItem["status"], "dim" | "default" | "bright" | "alert"> =
  {
    completed: "default",
    in_progress: "bright",
    pending: "default",
    cancelled: "dim",
    blocked: "alert",
  };

/** Recency fade (§3 hierarchy = brightness): the row at the frontier — where work
 *  currently is — reads at full brightness, each step away dims. Stepped values,
 *  not a gradient: deterministic readout, no easing (§8). */
const fade = (distance: number) =>
  distance === 0
    ? "opacity-100"
    : distance === 1
      ? "opacity-75"
      : distance === 2
        ? "opacity-50"
        : "opacity-30";

/** The agent's task list for this thread.
 *
 *  Always shows a compact window around the frontier — the running task, else the next
 *  pending one, else the last item of a finished plan — so progress is legible at a
 *  glance with no click: green squares for done, blue for running, empty bordered
 *  squares for what's left. Longer plans fold to the window behind an explicit
 *  +N MORE control; expanding lists every row.
 *
 *  Presentation only: the backend owns the list and nothing here can change it. There is
 *  deliberately no edit affordance — the plan is the agent's account of its own work, and
 *  an operator edit would silently disagree with what the model reads back.
 */
export function PlanPanel(props: { items: () => PlanItem[] }): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);

  const items = () => props.items();
  const active = createMemo(() =>
    items().find((i) => i.status === "in_progress"),
  );
  const done = createMemo(
    () => items().filter((i) => i.status === "completed").length,
  );
  // Cancelled tasks leave the denominator: the question the count answers is "how much is
  // left to do", and a cancelled task is not left to do.
  const total = createMemo(
    () => items().filter((i) => i.status !== "cancelled").length,
  );

  // Where the work currently is: the running task, else the next pending one,
  // else the last item (a finished plan reads from its end).
  const frontier = createMemo(() => {
    const list = items();
    if (list.length === 0) return -1;
    const running = list.findIndex((i) => i.status === "in_progress");
    if (running !== -1) return running;
    const next = list.findIndex((i) => i.status === "pending");
    if (next !== -1) return next;
    return list.length - 1;
  });

  // Rows on screen: the full list when expanded, else a WINDOW-row slice starting two
  // before the frontier (two done behind it, the frontier itself, up to two ahead).
  const visible = createMemo(() => {
    const list = items();
    if (expanded()) return list.map((item, index) => ({ item, index }));
    const start = Math.max(0, frontier() - 2);
    return list
      .slice(start, start + WINDOW)
      .map((item, i) => ({ item, index: start + i }));
  });

  const hidden = createMemo(() => items().length - visible().length);

  return (
    <Show when={items().length > 0}>
      <Panel
        label="PLAN"
        flush
        meta={
          <Row gap={2} align="center">
            {/* Tabular figures line up as the count changes mid-turn (§3). */}
            <Text variant="label" tone="bright" class="tabular-nums">
              {done()}/{total()}
            </Text>
            <Show when={active()} fallback={<StatusFlag>IDLE</StatusFlag>}>
              {/* Info blue, not warn amber: the running task is live data — the same
                  meaning STREAMING carries in the header, and the square below it. */}
              <StatusFlag status="info" dot pulse>
                ACTIVE
              </StatusFlag>
            </Show>
          </Row>
        }
      >
        <ol>
          <For each={visible()}>
            {({ item, index }) => (
              <li
                class={cx(
                  "flex items-center gap-2 px-3 py-1",
                  fade(Math.abs(index - frontier())),
                )}
              >
                <span
                  class={cx("size-3 shrink-0", SQUARE[item.status])}
                  aria-hidden
                />
                <Text
                  variant="body"
                  tone={TONE[item.status]}
                  class={cx(
                    "truncate",
                    item.status === "cancelled" && "line-through",
                  )}
                >
                  {item.status === "in_progress"
                    ? (item.active_form ?? item.content)
                    : item.content}
                </Text>
              </li>
            )}
          </For>
        </ol>
        <Show when={hidden() > 0}>
          <button
            type="button"
            class="flex w-full items-center gap-2 border-t border-line px-3 py-1 text-left"
            aria-expanded={expanded()}
            onClick={() => setExpanded((v) => !v)}
          >
            <Icon
              name={expanded() ? "chevron-up" : "chevron-down"}
              size={12}
              class="text-dim"
            />
            <Text variant="label" tone="dim">
              {expanded() ? "COLLAPSE" : `+${hidden()} MORE`}
            </Text>
          </button>
        </Show>
      </Panel>
    </Show>
  );
}
