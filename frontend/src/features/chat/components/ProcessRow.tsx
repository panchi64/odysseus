import { Show, children, type JSX } from "solid-js";
import { Icon, Text, cx, type IconName } from "~/ui";

/** The `·` between segments of one row. Quiet enough to read as punctuation
 *  rather than as another value. */
export function Sep(): JSX.Element {
  return (
    <Text variant="micro" tone="dim" class="shrink-0 opacity-50 select-none">
      ·
    </Text>
  );
}

/** One row of the agent's process: `chevron · glyph · Label · …` with an optional
 *  cluster pinned right.
 *
 *  Every kind of work in a turn renders through this — a tool call, a settled
 *  reasoning trace, the work log's own header — because they sit in one column on
 *  one rail and a column only reads as a sequence if its rows share an anatomy.
 *  They used to be three separate idioms: the tool row had a glyph, a detail and
 *  a right cluster; the reasoning accordion had a bare chevron and a word; the
 *  work log header had a shouted uppercase string. Three species on one rail is
 *  why the turn read as a log rather than as the agent narrating its work.
 *
 *  The truncation rules here are the load-bearing part and are easy to lose.
 *
 *  Every segment carries `truncate`, because `overflow:hidden` is what lets a flex
 *  item shrink below its content at all — without it the row does not truncate, it
 *  overflows, and a `shrink-0` segment inside this `min-w-0 flex-1` button escapes
 *  the button's box and paints over the cluster to its right.
 *
 *  **The label is the exception, and it is bounded rather than pinned.** Leaving it
 *  to plain flex was the old rule, on the theory that flex shrinks the longest
 *  segment hardest so the shortest survives. It does not survive: at 375px a row
 *  read `R… · backend/ap… · 412 li…`, and the *label* is the one segment that must
 *  not go — glyph plus label is how a column of rows is parsed before a word of
 *  detail is read. So it takes `shrink-0` to opt out of the squeeze, and
 *  `max-w-[45%]` so a long label ("Host command", a humanized `external_*` name)
 *  still cannot run past its share and out of the box. The detail beside it absorbs
 *  the loss instead, which is the right place for it: a truncated path is still
 *  recognizable, a truncated verb is not. */
export function ProcessRow(props: {
  open: boolean;
  onToggle: () => void;
  /** The family glyph. Omitted only where the row has no kind to name. */
  icon?: IconName;
  /** Tone class for the glyph — how a row carries its state without a word. */
  iconClass?: string;
  /** The row's name, in the interface's voice: "Read", "Reasoning", "Work log". */
  label: string;
  /** Everything between the label and the right cluster. Segments supply their
   *  own `Sep`, since only the caller knows which of them are present. */
  children?: JSX.Element;
  /** Pinned right — elapsed time, a copy button, an alert flag. */
  trailing?: JSX.Element;
  /** Full accessible name for the trigger, when the label alone is ambiguous
   *  (a tool row's label is the short human one, not the registry name). */
  title?: string;
  class?: string;
}): JSX.Element {
  const trailing = children(() => props.trailing);
  return (
    <div
      /* No hover fill here by default: a row that sits on a card wants one, and a
         row that is ambient chrome on the page does not (§10.2 — a card is a
         claim on attention, and the work log's own header is the least
         attention-worthy thing in a turn). Callers that own a surface pass
         `hover:bg-raised` themselves. */
      class={cx(
        "flex w-full items-center justify-between gap-2 pr-1.5 transition-colors",
        props.class,
      )}
    >
      <button
        type="button"
        aria-expanded={props.open}
        onClick={(e) => {
          // A row nested inside its own clickable wrapper would otherwise toggle
          // twice and appear inert.
          e.stopPropagation();
          props.onToggle();
        }}
        class="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left"
        title={props.title}
      >
        <Icon
          name={props.open ? "chevron-down" : "chevron-right"}
          size={12}
          class="text-dim"
        />
        <Show when={props.icon}>
          {(name) => (
            <Icon
              name={name()}
              size={12}
              class={props.iconClass ?? "text-dim"}
            />
          )}
        </Show>
        <Text
          variant="label"
          tone="bright"
          class="max-w-[45%] shrink-0 truncate"
        >
          {props.label}
        </Text>
        {props.children}
      </button>
      {/* `children()` and not `props.trailing` read twice. Solid props are
          getters, so reading one in `Show`'s condition AND again as the span's
          child builds the whole cluster twice and throws the first copy away —
          and because the condition is a memo that tracks whatever the cluster
          read while being built, it does it again on every `status`/`elapsedMs`
          change. This resolves it once and hands the same nodes to both. */}
      <Show when={trailing()}>
        <span class="flex shrink-0 items-center gap-2">{trailing()}</span>
      </Show>
    </div>
  );
}
