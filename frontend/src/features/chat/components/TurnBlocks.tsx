import {
  For,
  Match,
  Show,
  Switch,
  createEffect,
  createMemo,
  createSignal,
  on,
  untrack,
  type JSX,
} from "solid-js";
import { Caret, Disclosure, LedEdge, Markdown, Reveal, Text, cx } from "~/ui";
import type {
  ApprovalBlock,
  ApprovalDecision,
  AssistantBlock,
  BlockKind,
  HostCommandBlock,
  TextBlock,
  ThinkingBlock,
  ToolBlock,
  ViewLiveBlock,
  ViewVersionBlock,
} from "../model";
import {
  groupBlocks,
  layoutItemKey,
  peekLatestTool,
  planTurnLayout,
  type BlockGroup,
  type LayoutItem,
} from "../blocks";
import { LIVE_KEY, snapshotKey, versionIcon, type ViewItem } from "../viewport";
import { ApprovalCard } from "./ApprovalCard";
import { HostCommandCard } from "./HostCommandCard";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";
import {
  INTERVAL_SEED,
  REVEAL_MS,
  extendSchedule,
  firstLiveIndex,
  nextInterval,
  revealDelay,
} from "../streamReveal";
import {
  classifyViewItem,
  viewItemTimeLabel,
  viewItemVersionLabel,
  ViewChip,
} from "./ViewChip";

type Resolve = (decisions: ApprovalDecision[]) => void | Promise<void>;
const noop: Resolve = () => {};

/** A chip's matching `ViewItem` (when the transcript's own View list carries
 *  one) plus its position in that chronologically-ordered list — the position
 *  is what `isNew` compares against the "seen through" pointer, rather than a
 *  fabricated per-render index. */
interface ChipLookupEntry {
  item: ViewItem;
  index: number;
}

interface RowHandlers {
  onResolveApproval?: Resolve;
  onResolveHostCommands?: Resolve;
  /** Open a View item (a version or the live head) in the side viewport, by key. */
  onOpenInView?: (key: string) => void;
  /** Keyed lookup of the conversation's View list — lets an inline chip show the
   *  same version/time metadata `ViewTimelineRail` shows for the same item. */
  chipLookup?: Map<string, ChipLookupEntry>;
  /** The matched item's index must exceed this to render its chip's NEW marker. */
  seenIndex?: number;
}

/** How a row spaces itself from the one above:
 *  - "none"    — first row, flush to the top.
 *  - "gap"     — separated by margin (no rail ink in the gap): a run boundary.
 *  - "connect" — separated by border-covered padding so a rail block's hairline
 *    runs unbroken into the rail block above it (one continuous timeline). */
type TopSpacing = "none" | "gap" | "connect";

/** Block kinds that render against the left timeline rail (process), as opposed
 *  to the full-width result blocks (answer text, artifacts, previews). */
const RAIL_KINDS: ReadonlySet<BlockKind> = new Set([
  "thinking",
  "tool",
  "host_command",
  "approval",
]);

/** The left rail that turns a stack of process blocks into a legible, ordered
 *  timeline — one of the few borders the system keeps, because an unbroken
 *  vertical line is the thing being communicated (§7).
 *
 *  At rest it is a hairline. While a block is live `LedEdge` lights it — the
 *  same rule, emitting, with the glow spilling leftward onto the page. That says
 *  "this is running" far more directly than a colour swap, and shifts nothing,
 *  since the rule keeps its width and the glow is a shadow. When `top="connect"`
 *  the gap
 *  above is *padding inside the border*, so the hairline joins the rail block
 *  above into one unbroken line; "gap" keeps the spacing outside the border so
 *  the line stops at a run boundary. Answer/artifact/preview render full-width
 *  (results lead; work recedes). */
function Rail(props: {
  active?: boolean;
  top?: TopSpacing;
  children: JSX.Element;
}): JSX.Element {
  return (
    <LedEdge
      lit={props.active}
      class={cx(
        "pl-3 transition-colors",
        props.top === "connect" && "pt-3",
        props.top === "gap" && "mt-3",
      )}
    >
      {props.children}
    </LedEdge>
  );
}

/** Margin for a full-width (non-rail) row — spacing always lives outside, since
 *  there's no rail to keep continuous. */
function fullWidthTop(top?: TopSpacing): string | undefined {
  return top && top !== "none" ? "mt-3" : undefined;
}

/** Subtrees the fade must not enter, because their contents are the machine's
 *  voice and the machine does not ease (§8). Code and samples are mono by
 *  element; `.katex` is neither voice, and threading spans through KaTeX's
 *  markup would be meddling with a layout we don't own. `.font-mono` catches
 *  anything that opted in by class.
 *
 *  `table` is here for three reasons that agree. A table is a dense data panel
 *  (§10) whose header band is already mono because a column header names a
 *  machine field — and it is mono by `font-family`, not by a class, so nothing
 *  else in this list would have caught it. Its cells are emitted values, which
 *  is the §2 test for the machine voice. And the eye reads a grid in two
 *  dimensions, so a reveal sweeping left-to-right through cells reads as
 *  flicker rather than as arrival — on top of the column widths still
 *  reflowing as rows stream in. */
const MACHINE_VOICE = "code, pre, kbd, samp, table, .katex, .font-mono";

/** Every animatable text node under `root`, in document order, with the absolute
 *  character index each one starts at. Machine-voice subtrees are rejected
 *  outright, so their characters are neither wrapped nor counted — the index
 *  space is *animatable* characters, which is what keeps it stable between
 *  passes, and it is what makes a code block land hard inside an answer that is
 *  easing in around it. Collected before any mutation, since splitting a node
 *  mid-walk would invalidate the walker. */
function animatableText(root: HTMLElement): {
  nodes: { node: Text; base: number }[];
  count: number;
} {
  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode: (node) => {
        if (node.nodeType !== Node.ELEMENT_NODE)
          return NodeFilter.FILTER_ACCEPT;
        // REJECT prunes the whole subtree; SKIP passes over the element itself
        // and keeps descending, which is what every other element wants.
        return (node as Element).matches(MACHINE_VOICE)
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_SKIP;
      },
    },
  );
  const nodes: { node: Text; base: number }[] = [];
  let count = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const node = n as Text;
    nodes.push({ node, base: count });
    count += node.data.length;
  }
  return { nodes, count };
}

/** One character, wrapped so it resolves in on its own schedule. */
function revealSpan(char: string, delay: number): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = "ody-token-in";
  // Duration comes from the same constant the schedule reasons about, so the
  // two can't drift; the delay is what carries this character's phase across a
  // re-render.
  span.style.setProperty("--reveal-ms", `${REVEAL_MS}ms`);
  span.style.animationDelay = `${delay}ms`;
  span.textContent = char;
  return span;
}

/**
 * Apply `starts` to the answer's DOM: every character still inside its reveal
 * window becomes a span carrying its own delay, and everything settled is left
 * as plain text. Extends the schedule to cover any newly-arrived characters and
 * returns it.
 *
 * Rebuilding the wrappers wholesale on each delta is deliberate — the trailing
 * block's DOM is new anyway, and re-deriving each character's delay from its
 * *absolute* start is exactly what lets a fade continue across that rebuild
 * rather than restarting. The work is bounded by the live window (roughly
 * `REVEAL_MS` worth of characters), not by the length of the answer.
 */
function applyReveal(
  root: HTMLElement,
  starts: number[],
  now: number,
  interval: number,
): number[] {
  const { nodes, count } = animatableText(root);
  starts = extendSchedule(starts, count, now, interval);
  const from = firstLiveIndex(starts, now);
  if (from >= count) return starts;

  for (const { node, base } of nodes) {
    const len = node.data.length;
    if (base + len <= from || !node.parentNode) continue;
    // Split the node once into "settled" and "still resolving", then rebuild
    // only the second half a character at a time.
    const cut = Math.max(0, from - base);
    const frag = document.createDocumentFragment();
    if (cut > 0)
      frag.appendChild(document.createTextNode(node.data.slice(0, cut)));
    for (let i = cut; i < len; i++) {
      const delay = revealDelay(starts[base + i], now);
      frag.appendChild(
        delay === null
          ? document.createTextNode(node.data[i])
          : revealSpan(node.data[i], delay),
      );
    }
    node.parentNode.replaceChild(frag, node);
  }
  return starts;
}

/** A passage of the answer — full-width and bright. The active, still-streaming
 *  passage carries the caret, resolves each arriving character in on its own
 *  schedule (§8, human register), and defers code-copy enhancement until it
 *  settles.
 *
 *  `streamStable` while live keeps the DOM of every settled block, so only the
 *  trailing block re-parses per delta — which is what stops KaTeX/markdown
 *  flicker. It is also why the reveal is scheduled in absolute time: that
 *  re-parse destroys anything mid-animation, and only a character that knows
 *  when it *started* can pick its fade back up rather than restarting it. See
 *  `streamReveal.ts`. */
function AnswerText(props: {
  text: string;
  active?: boolean;
  streaming?: boolean;
}): JSX.Element {
  const live = () => Boolean(props.active && props.streaming);

  /* Latched, and this is what stops the screen flashing when a run finishes.
     `Markdown` renders a *different element* for `streamStable` than for its
     default path — it has to, since Solid's `innerHTML` prop can't coexist with
     rendered children on one node. Passing `live()` straight through therefore
     flipped that flag at the exact moment the answer completed, and Solid tore
     down the entire rendered answer and rebuilt it: a full re-parse, a fresh
     DOM, KaTeX re-rendered, every `pre` and `table` re-wrapped. On a long answer
     that is a visible flash at the worst possible moment — the instant the
     operator starts reading.

     Once a passage has streamed it keeps the block path forever. The two paths
     render the same content (the block path exists to replicate the prose
     cascade at the block-wrapper level), so there is nothing to switch back
     for. A message that never streamed — history, a settled turn — never takes
     the block path at all, which is the cheaper read for a long transcript. */
  const [streamStable, setStreamStable] = createSignal(live());
  createEffect(() => {
    if (live()) setStreamStable(true);
  });

  let host: HTMLDivElement | undefined;
  // Absolute start time per animatable character. Empty until the passage goes
  // live; a message that arrives complete (history, a settled turn) never
  // schedules anything and so renders without animating.
  let starts: number[] = [];
  // Running estimate of the gap between deltas, which is what the stagger is
  // paced against — see `streamReveal.ts`. Seeded rather than measured from the
  // first delta, since there is nothing to measure against yet.
  let interval = INTERVAL_SEED;
  let lastDelta = 0;

  createEffect(() => {
    // Read the source so this effect re-runs on every delta (the value itself
    // is not needed — the DOM Markdown just committed is what gets walked).
    void props.text;
    // A passage that never streamed (history, a settled turn) schedules nothing
    // and renders instantly. One that has streamed keeps going for a final pass
    // after `live()` drops: the run's last characters land in the same tick the
    // stream closes, and bailing here made them the one part of the answer that
    // appeared without resolving — a pop right at the end of an otherwise smooth
    // reveal.
    if (!host || (!live() && starts.length === 0)) return;
    // Let Markdown commit its own DOM for this delta first.
    queueMicrotask(() => {
      if (!host) return;
      const now = performance.now();
      // Attaching to a passage that already has text (a resumed stream): treat
      // what is on screen as settled rather than animating the whole thing in.
      if (starts.length === 0) {
        const existing = host.textContent?.length ?? 0;
        starts = Array.from({ length: existing }, () => now - REVEAL_MS);
      }
      if (lastDelta) interval = nextInterval(interval, now - lastDelta);
      lastDelta = now;
      starts = applyReveal(host, starts, now, interval);
    });
  });

  return (
    <div>
      <div ref={host} class="inline">
        {/* `copyCode` stays on THROUGHOUT, including while streaming. It used to
            be gated on `!live()` to save a DOM scan per delta, but that gate was
            paid for at the worst moment: flipping it on completion ran the
            enhancement pass over a finished answer, and that pass *physically
            moves* every `pre` and `table` — out of the tree and back inside a
            wrapper. Re-laying-out and re-rasterizing every code block the
            instant the answer settles is a redraw the operator sees.

            Enhancing as we go does the same work incrementally on the trailing
            block instead, and leaves nothing to do at the end. The buttons are
            hidden until their block is hovered, so nothing appears mid-stream
            either. */}
        <Markdown class="inline" streamStable={streamStable()}>
          {props.text}
        </Markdown>
      </div>
      <Show when={live()}>
        {" "}
        <Caret class="text-bright" />
      </Show>
    </div>
  );
}

/** A chip's kindWord/meta/isNew, derived from its matching `ViewItem` (when the
 *  turn's own View list carries one) via the same helpers `ViewTimelineRail`
 *  uses for the identical data. No match (e.g. cold history whose item fell out
 *  of the list) falls back to `ViewChip`'s own icon-derived defaults. */
function chipMeta(
  lookup: Map<string, ChipLookupEntry> | undefined,
  seenIndex: number | undefined,
  key: string,
): { kindWord?: string; meta?: string; isNew: boolean } {
  const entry = lookup?.get(key);
  if (!entry) return { isNew: false };
  return {
    kindWord: classifyViewItem(entry.item).word,
    meta: viewItemVersionLabel(entry.item) ?? viewItemTimeLabel(entry.item),
    isNew: entry.index > (seenIndex ?? -1),
  };
}

/** Render one block group by kind. Approvals and host commands arrive as a
 *  group (consecutive blocks batched) so their cards keep one shared decision. */
function BlockRow(
  props: {
    group: BlockGroup;
    /** This group is the turn's live, trailing block. */
    active?: boolean;
    streaming?: boolean;
    forceOpen?: boolean;
    top?: TopSpacing;
  } & RowHandlers,
): JSX.Element {
  const g = () => props.group;
  return (
    <Switch>
      <Match when={g().kind === "text"}>
        <div class={fullWidthTop(props.top)}>
          <AnswerText
            text={(g().blocks[0] as TextBlock).text}
            active={props.active}
            streaming={props.streaming}
          />
        </div>
      </Match>
      <Match when={g().kind === "view_version"}>
        {(() => {
          const b = g().blocks[0] as ViewVersionBlock;
          const key = snapshotKey(b.snapshotId);
          const chip = () => chipMeta(props.chipLookup, props.seenIndex, key);
          return (
            <div class={fullWidthTop(props.top)}>
              <ViewChip
                icon={versionIcon(b.previewKind)}
                label={b.title || "Version"}
                kindWord={chip().kindWord}
                meta={chip().meta}
                isNew={chip().isNew}
                onOpen={() => props.onOpenInView?.(key)}
              />
            </div>
          );
        })()}
      </Match>
      <Match when={g().kind === "view_live"}>
        {(() => {
          const live = (g().blocks[0] as ViewLiveBlock).live;
          const chip = () =>
            chipMeta(props.chipLookup, props.seenIndex, LIVE_KEY);
          return (
            <div class={fullWidthTop(props.top)}>
              <ViewChip
                icon="play"
                label={live.title || "Live view"}
                live
                kindWord={chip().kindWord}
                meta={chip().meta}
                isNew={chip().isNew}
                onOpen={() => props.onOpenInView?.(LIVE_KEY)}
              />
            </div>
          );
        })()}
      </Match>
      <Match when={g().kind === "thinking"}>
        <Rail active={props.active} top={props.top}>
          <ReasoningBlock
            reasoning={(g().blocks[0] as ThinkingBlock).text}
            open={props.forceOpen}
            active={props.active}
            streaming={props.streaming}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "tool"}>
        <Rail active={props.active} top={props.top}>
          <ToolCallCard
            tool={(g().blocks[0] as ToolBlock).tool}
            open={props.forceOpen}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "host_command"}>
        <Rail active={props.active} top={props.top}>
          <HostCommandCard
            commands={(g().blocks as HostCommandBlock[]).map((b) => b.command)}
            open={props.forceOpen}
            onSubmit={props.onResolveHostCommands ?? noop}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "approval"}>
        <Rail active={props.active} top={props.top}>
          <ApprovalCard
            approvals={(g().blocks as ApprovalBlock[]).map((b) => b.approval)}
            onSubmit={props.onResolveApproval ?? noop}
          />
        </Rail>
      </Match>
    </Switch>
  );
}

/** The top spacing for the item at `index`: nothing for the first, a connected
 *  rail when this and the previous row are both rail blocks, otherwise a plain
 *  gap (run boundary). */
function topSpacing(items: LayoutItem[], index: number): TopSpacing {
  if (index === 0) return "none";
  const isRail = (it: LayoutItem) =>
    it.type === "group" && RAIL_KINDS.has(it.group.kind);
  return isRail(items[index]) && isRail(items[index - 1]) ? "connect" : "gap";
}

/** The compacted work log: one run of consecutive process blocks folded into a
 *  single accordion that peeks the latest call + its rationale, so a busy turn
 *  doesn't bury the screen. Expanding restores the full ordered run. */
function WorkLogAccordion(
  props: {
    groups: BlockGroup[];
    /** Open state is owned by the turn (keyed by a stable id) so it survives the
     *  remount when a streaming delta rebuilds the layout — a local signal here
     *  would reset on every new block. */
    open: boolean;
    onToggle: () => void;
    forceOpen?: boolean;
    top?: TopSpacing;
  } & RowHandlers,
): JSX.Element {
  const peek = createMemo(() => peekLatestTool(props.groups));

  return (
    <div class={fullWidthTop(props.top)}>
      <Disclosure
        label={`WORK LOG · ${props.groups.length} ${
          props.groups.length === 1 ? "Step" : "Steps"
        }`}
        open={props.open}
        onToggle={() => props.onToggle()}
        triggerClass="w-full gap-2"
        trailing={
          <Show when={!props.open && peek()}>
            {(p) => (
              <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
                {p().name}
                {p().rationale ? ` — ${p().rationale}` : ""}
              </Text>
            )}
          </Show>
        }
      >
        {/* Folded groups are mostly rail blocks (they connect into one line); a
            View chip in the run renders full-width between them. */}
        <For each={props.groups}>
          {(group, i) => (
            <BlockRow
              group={group}
              top={i() === 0 ? "none" : "connect"}
              forceOpen={props.forceOpen}
              onResolveApproval={props.onResolveApproval}
              onResolveHostCommands={props.onResolveHostCommands}
              chipLookup={props.chipLookup}
              seenIndex={props.seenIndex}
            />
          )}
        </For>
      </Disclosure>
    </div>
  );
}

/** Render an assistant turn as its ordered, interleaved blocks — the agent's
 *  true think → tool → text → … sequence — with a per-block rail for separation
 *  and a folded work log when the process grows long. */
export function TurnBlocks(
  props: {
    blocks: AssistantBlock[] | undefined;
    streaming?: boolean;
    /** Expand-all / collapse-all from the turn header. */
    forceOpen?: boolean;
    /** The conversation's consolidated View list, for the inline chips' own
     *  version/time/NEW metadata — see `RowHandlers.chipLookup`. */
    viewItems?: () => ViewItem[];
    /** The "seen through" pointer — see `RowHandlers.seenIndex`. */
    seenKey?: () => string | null;
  } & Omit<RowHandlers, "chipLookup" | "seenIndex">,
): JSX.Element {
  // Memoized so a text/thinking delta (which doesn't change block *structure*)
  // doesn't re-group/re-plan, and so `activeId` reuses the same grouping rather
  // than recomputing it — one structural pass per real change, not per token.
  const groups = createMemo(() => groupBlocks(props.blocks));
  const layout = createMemo(() =>
    planTurnLayout(groups(), { streaming: props.streaming }),
  );

  /* `<For>` is REFERENCE-keyed, and `planTurnLayout` mints fresh objects on
     every call — so iterating it directly made every row of the turn new on
     every recompute, and the whole turn was torn down and re-rendered. That
     happened on each new block, and again when `streaming` flipped at the end of
     a run (the plan reads it, to keep the live tail out of a work log). The
     second one is a full redraw of the turn at the moment the operator starts
     reading it.

     So iterate stable KEYS — strings compare by value, so an unchanged row is
     unchanged — and look the item up through a memo, which keeps the row's props
     live. A row is now created once and only genuinely new or regrouped rows
     move. */
  const keys = createMemo(() => layout().map(layoutItemKey));
  const byKey = createMemo(
    () =>
      new Map<string, LayoutItem>(
        layout().map((item) => [layoutItemKey(item), item] as const),
      ),
  );
  const indexOfKey = (key: string): number => keys().indexOf(key);
  // One key -> {item, index} lookup for the turn's inline chips, built once per
  // View-list change (not per chip) — mirrors `ViewTimelineRail`'s own use of
  // `classifyViewItem`/`viewItemVersionLabel`/`viewItemTimeLabel` for the same
  // data. `seenIndex` is the "seen through" key's position in that same
  // chronological list (-1 when unset or no longer present, e.g. a rewind).
  const chipLookup = createMemo(() => {
    const items = props.viewItems?.() ?? [];
    const map = new Map<string, ChipLookupEntry>();
    items.forEach((item, index) => map.set(item.key, { item, index }));
    return map;
  });
  const seenIndex = createMemo(() => {
    const items = props.viewItems?.() ?? [];
    const key = props.seenKey?.() ?? null;
    return key ? items.findIndex((i) => i.key === key) : -1;
  });
  // While streaming, the trailing group is the live one.
  const activeId = createMemo(() => {
    const gs = groups();
    return props.streaming && gs.length ? gs[gs.length - 1].id : null;
  });

  // Each work log's open state lives here, keyed by its run's first-block id (a
  // stable id), so it survives the `<For>` remount when a streaming delta
  // rebuilds `layout()`. Toggling the turn-level expand/collapse-all wipes the
  // per-log overrides so the global control re-takes command of every log.
  const [openLogs, setOpenLogs] = createSignal<Record<string, boolean>>({});
  createEffect(
    on(
      () => props.forceOpen,
      () => setOpenLogs({}),
      { defer: true },
    ),
  );
  const logOpen = (id: string): boolean =>
    openLogs()[id] ?? props.forceOpen ?? false;
  const toggleLog = (id: string): void => {
    setOpenLogs({ ...openLogs(), [id]: !logOpen(id) });
  };

  /* Whether a row should materialize as it arrives.

     Latched at mount, and deliberately NOT reactive. A live turn's blocks appear
     one at a time — reasoning, then a tool call, then the answer — and each one
     popping into place is the jolt between the operator's message and the
     model's reply. A turn read from history mounts all of its rows at once, and
     animating those would be a whole transcript moving on load, which §8
     forbids. Reading `streaming` reactively would be worse still: the wrapper
     element would change when the run ended and flash the entire turn, which is
     the bug just fixed one component over. */
  const revealRows = untrack(() => Boolean(props.streaming));

  return (
    <div>
      <For each={keys()}>
        {(key) => {
          // Narrowed per kind, so each arm reads its own shape without casts.
          // Both stay live: the item object behind a key is replaced on every
          // recompute, and reading it through these is what lets the row update
          // in place instead of being rebuilt.
          const item = () => byKey().get(key);
          const log = () => {
            const it = item();
            return it?.type === "worklog" ? it : undefined;
          };
          const group = () => {
            const it = item();
            return it?.type === "group" ? it.group : undefined;
          };
          const top = () => topSpacing(layout(), indexOfKey(key));
          const row = (
            <Show
              when={log()}
              fallback={
                <Show when={group()}>
                  {(g) => (
                    <BlockRow
                      group={g()}
                      active={g().id === activeId()}
                      streaming={props.streaming}
                      top={top()}
                      forceOpen={props.forceOpen}
                      onResolveApproval={props.onResolveApproval}
                      onResolveHostCommands={props.onResolveHostCommands}
                      onOpenInView={props.onOpenInView}
                      chipLookup={chipLookup()}
                      seenIndex={seenIndex()}
                    />
                  )}
                </Show>
              }
            >
              {(l) => (
                <WorkLogAccordion
                  groups={l().groups}
                  open={logOpen(l().groups[0].id)}
                  onToggle={() => toggleLog(l().groups[0].id)}
                  top={top()}
                  forceOpen={props.forceOpen}
                  onResolveApproval={props.onResolveApproval}
                  onResolveHostCommands={props.onResolveHostCommands}
                  chipLookup={chipLookup()}
                  seenIndex={seenIndex()}
                />
              )}
            </Show>
          );
          /* A plain fade, not a rise: these rows sit against a continuous
             timeline rail, and anything that moved would drag the rail's
             hairline with it. Materializing in place says "this arrived"
             without disturbing the structure it arrived into. */
          return revealRows ? <Reveal>{row}</Reveal> : row;
        }}
      </For>
    </div>
  );
}
