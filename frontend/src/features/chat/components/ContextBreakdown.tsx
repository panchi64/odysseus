import { For, Show, createSignal, type JSX } from "solid-js";
import { compactCount, pct } from "~/lib/format";
import { Icon, Text } from "~/ui";
import type { ContextUsage } from "../model";
import {
  contextRows,
  type ContextDetail,
  type ContextRow,
} from "./contextRows";

/** The same severity the ring carries, on the panel's headline figure. It differs from
 *  the ring's map in one place: at rest the ring is `dim` (a gauge with nothing to say
 *  should recede) but the headline is `bright`, because a panel the operator
 *  deliberately opened is not competing for attention — they are already looking at it,
 *  and dimming the one number they opened it to read would be restraint pointed at the
 *  wrong thing. */
const HEADLINE_TONE = {
  nominal: "bright",
  warn: "warn",
  alert: "alert",
} as const;

const tokens = (n: number) => n.toLocaleString("en-US");

/** What the window is holding, and what is left of it.
 *
 *  The ring outside answers *how full*; this answers *full of what*, and the answers
 *  lead to different actions — a thread heavy with messages wants a compaction, one
 *  heavy with tool schemas wants fewer tools switched on, one heavy with tool *results*
 *  wants the tools that return too much. That is the whole reason the split is worth a
 *  click rather than a tooltip.
 *
 *  **Three rows, then as many as the operator asks for.** The groups are the reading;
 *  the itemisation beneath each is the decision, and it stays folded until it is wanted
 *  because a dozen rows at rest is a panel to study rather than one to glance at. Which
 *  rows exist at all is the backend's: it emits a segment only once it weighs something,
 *  so a fresh thread shows two lines and a long tool-heavy one grows the rest as they
 *  start costing the window. Nothing here renders a placeholder for a row that did not
 *  arrive. */
export function ContextBreakdown(props: { usage: ContextUsage }): JSX.Element {
  const rows = () => contextRows(props.usage);
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
          ~{compactCount(props.usage.used, true)} /{" "}
          {compactCount(props.usage.window, true)}
        </Text>
      </div>

      <Bar rows={rows()} />

      <div class="flex flex-col">
        <For each={rows()}>{(row) => <Row row={row} />}</For>
      </div>

      <Show when={!props.usage.parts}>
        <Text variant="micro" tone="dim">
          The breakdown appears once a turn has run — the tool schemas and
          system prompt aren't in the stored transcript, so they're measured as
          a message is sent.
        </Text>
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
 *  Every row is drawn against the **window**, free space included, so the bar *is* the
 *  window: the filled run is the fraction the ring draws and the pale tail is the room
 *  left. A bar normalised to what's used would show a full-width strip on a 5%-full
 *  thread, which says the opposite of what the ring beside it says. */
function Bar(props: { rows: ContextRow[] }): JSX.Element {
  return (
    <div class="flex h-1 w-full overflow-hidden rounded-ctl bg-line">
      <For each={props.rows}>
        {(row) => (
          <div
            class={`h-full ${row.fill}`}
            style={{ width: `${row.share}%` }}
          />
        )}
      </For>
    </div>
  );
}

/** One group: its swatch, its figures, and — where the backend itemised it — the rows
 *  it is made of, one click away.
 *
 *  A row with no detail is rendered as a plain line rather than an inert button, so the
 *  chevron never promises something that isn't there. */
function Row(props: { row: ContextRow }): JSX.Element {
  const [open, setOpen] = createSignal(false);
  const expandable = () => props.row.detail.length > 0;
  return (
    <div>
      <button
        type="button"
        disabled={!expandable()}
        aria-expanded={expandable() ? open() : undefined}
        onClick={() => setOpen(!open())}
        class="group flex w-full items-center gap-2 py-1 text-left enabled:cursor-pointer"
      >
        <span class="flex size-3 shrink-0 items-center justify-center">
          <Show
            when={expandable()}
            fallback={<span class={`size-2 rounded-ctl ${props.row.fill}`} />}
          >
            <Icon
              name={open() ? "chevron-down" : "chevron-right"}
              size={12}
              class="text-dim group-hover:text-bright"
            />
          </Show>
        </span>
        <Show when={expandable()}>
          <span class={`size-2 shrink-0 rounded-ctl ${props.row.fill}`} />
        </Show>
        <Text variant="label" tone="default" class="min-w-0 truncate">
          {props.row.label}
        </Text>
        <span class="ml-auto flex shrink-0 items-baseline gap-3">
          <Text variant="micro" tone="dim" class="tabular-nums">
            ~{compactCount(props.row.tokens, true)}
          </Text>
          {/* Fixed-width so the column reads down as a column: a breakdown is scanned
              vertically, and shares that start at different x-positions have to be
              read one at a time. */}
          <Text variant="micro" tone="dim" class="w-11 text-right tabular-nums">
            {pct(props.row.share, 1)}
          </Text>
        </span>
      </button>

      <Show when={open()}>
        <div class="mb-1 ml-5 flex flex-col border-l border-line pl-3">
          <For each={props.row.detail}>{(item) => <Detail item={item} />}</For>
        </div>
      </Show>
    </div>
  );
}

/** One line item inside a group. Dimmer and countable: the figures are already ranked
 *  by size, so what the operator needs beside them is the population behind the number
 *  — 22K of schemas is a lot of text, 22K across 68 tools is a catalog to prune. */
function Detail(props: { item: ContextDetail }): JSX.Element {
  return (
    <div class="flex items-baseline gap-3 py-0.5">
      <Text variant="micro" tone="dim" class="min-w-0 truncate">
        {props.item.label}
      </Text>
      <span class="ml-auto flex shrink-0 items-baseline gap-3">
        <Show when={props.item.count !== null}>
          <Text variant="micro" tone="dim" class="tabular-nums">
            {props.item.count} tools
          </Text>
        </Show>
        <Text variant="micro" tone="default" class="tabular-nums">
          ~{compactCount(props.item.tokens, true)}
        </Text>
        {/* The empty column the group row spends on its share, so a child's figure
            sits directly under its parent's rather than under the percentage beside
            it — the two columns mean different things and reading down a column is
            the only reason to have columns. */}
        <span class="w-11" aria-hidden="true" />
      </span>
    </div>
  );
}
