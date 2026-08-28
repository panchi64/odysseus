import {
  For,
  Match,
  Show,
  Switch,
  createEffect,
  createMemo,
  createSignal,
  on,
  type JSX,
} from "solid-js";
import { Caret, Disclosure, Markdown, Text, cx } from "~/ui";
import type {
  ApprovalBlock,
  ApprovalDecision,
  AssistantBlock,
  BlockKind,
  HostCommandBlock,
  TextBlock,
  ThinkingBlock,
  ToolBlock,
  ViewDocumentBlock,
  ViewLiveBlock,
  ViewVersionBlock,
} from "../model";
import {
  groupBlocks,
  peekLatestTool,
  planTurnLayout,
  type BlockGroup,
  type LayoutItem,
} from "../blocks";
import {
  LIVE_KEY,
  documentKey,
  snapshotKey,
  versionIcon,
  type ViewItem,
} from "../viewport";
import { ApprovalCard } from "./ApprovalCard";
import { HostCommandCard } from "./HostCommandCard";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";
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
 *  timeline. A 1px hairline — the workhorse divider that enforces structure
 *  (§2) — coloured to mark the live block (brightness/hue, not width, so the
 *  block never reflows when it goes active, §1). When `top="connect"` the gap
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
    <div
      class={cx(
        "border-l pl-3 transition-colors",
        props.active ? "border-info" : "border-line",
        props.top === "connect" && "pt-3",
        props.top === "gap" && "mt-3",
      )}
    >
      {props.children}
    </div>
  );
}

/** Margin for a full-width (non-rail) row — spacing always lives outside, since
 *  there's no rail to keep continuous. */
function fullWidthTop(top?: TopSpacing): string | undefined {
  return top && top !== "none" ? "mt-3" : undefined;
}

/** Wrap every character past `seen` in a span that fades itself in, and report
 *  the new total. Text nodes are collected before any mutation, since splitting
 *  one mid-walk would invalidate the walker.
 *
 *  Older text is left as plain, unwrapped nodes, so it carries no animation even
 *  when Markdown replaces the block's DOM on the next delta — only the newly
 *  arrived run ever animates. A run whose animation is interrupted by the next
 *  delta simply lands at full opacity, which is the intended effect: the token
 *  at the head of the stream is the one that fades. */
function fadeInTextPast(root: HTMLElement, seen: number): number {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const pending: { node: Text; offset: number }[] = [];
  let count = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const node = n as Text;
    const len = node.data.length;
    if (count + len > seen) {
      pending.push({ node, offset: Math.max(0, seen - count) });
    }
    count += len;
  }
  for (const { node, offset } of pending) {
    const tail = offset > 0 ? node.splitText(offset) : node;
    if (!tail.parentNode || !tail.data) continue;
    const span = document.createElement("span");
    span.className = "ody-token-in";
    tail.parentNode.insertBefore(span, tail);
    span.appendChild(tail);
  }
  return count;
}

/** A passage of the answer — full-width and bright. The active, still-streaming
 *  passage carries the caret, fades in each arriving run of text (§8, human
 *  register), and defers code-copy enhancement until it settles.
 *
 *  `streamStable` while live keeps the DOM of every settled block, so only the
 *  trailing block re-parses per delta — which is both what stops KaTeX/markdown
 *  flicker and what keeps the fade confined to genuinely new text. */
function AnswerText(props: {
  text: string;
  active?: boolean;
  streaming?: boolean;
}): JSX.Element {
  const live = () => Boolean(props.active && props.streaming);
  let host: HTMLDivElement | undefined;
  // Characters already on screen. A message that arrives complete (history,
  // a settled turn) starts fully "seen" so it renders without animating.
  let seen = live() ? 0 : Infinity;

  createEffect(() => {
    // Track the source so this re-runs on every delta.
    const text = props.text;
    if (!host || !live()) {
      seen = Infinity;
      return;
    }
    // Let Markdown commit its own DOM for this delta first.
    queueMicrotask(() => {
      if (!host) return;
      seen = fadeInTextPast(host, seen === Infinity ? text.length : seen);
    });
  });

  return (
    <div>
      <div ref={host} class="inline">
        <Markdown class="inline" copyCode={!live()} streamStable={live()}>
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
      <Match when={g().kind === "view_document"}>
        {(() => {
          const b = g().blocks[0] as ViewDocumentBlock;
          const key = documentKey(b.documentId, b.version);
          const chip = () => chipMeta(props.chipLookup, props.seenIndex, key);
          return (
            <div class={fullWidthTop(props.top)}>
              <ViewChip
                icon="file"
                label={b.title || "Document"}
                kindWord={chip().kindWord}
                meta={chip().meta}
                isNew={chip().isNew}
                onOpen={() => props.onOpenInView?.(key)}
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

  return (
    <div>
      <For each={layout()}>
        {(item, i) =>
          item.type === "worklog" ? (
            <WorkLogAccordion
              groups={item.groups}
              open={logOpen(item.groups[0].id)}
              onToggle={() => toggleLog(item.groups[0].id)}
              top={topSpacing(layout(), i())}
              forceOpen={props.forceOpen}
              onResolveApproval={props.onResolveApproval}
              onResolveHostCommands={props.onResolveHostCommands}
              chipLookup={chipLookup()}
              seenIndex={seenIndex()}
            />
          ) : (
            <BlockRow
              group={item.group}
              active={item.group.id === activeId()}
              streaming={props.streaming}
              top={topSpacing(layout(), i())}
              forceOpen={props.forceOpen}
              onResolveApproval={props.onResolveApproval}
              onResolveHostCommands={props.onResolveHostCommands}
              onOpenInView={props.onOpenInView}
              chipLookup={chipLookup()}
              seenIndex={seenIndex()}
            />
          )
        }
      </For>
    </div>
  );
}
