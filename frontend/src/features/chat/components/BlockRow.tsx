import { Match, Switch, type JSX } from "solid-js";
import { LedEdge, cx } from "~/ui";
import type {
  ApprovalDecision,
  BlockKind,
  CompactionProgressBlock,
  ContextBlock,
  HostCommandBlock,
  ReviewBlock,
  TextBlock,
  ThinkingBlock,
  ToolBlock,
  ViewLiveBlock,
  ViewVersionBlock,
} from "../model";
import type { BlockGroup, LayoutItem } from "../blocks";
import { LIVE_KEY, snapshotKey, versionIcon, type ViewItem } from "../viewport";
import { AnswerText } from "./AnswerText";
import { CompactionProgressCard } from "./CompactionProgressCard";
import { ContextInjectionCard } from "./ContextInjectionCard";
import { HostCommandCard } from "./HostCommandCard";
import { ReasoningBlock } from "./ReasoningBlock";
import { ReviewCard } from "./ReviewCard";
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
export interface ChipLookupEntry {
  item: ViewItem;
  index: number;
}

export interface RowHandlers {
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
export type TopSpacing = "none" | "gap" | "connect";

/** Block kinds that render against the left timeline rail (process), as opposed
 *  to the full-width result blocks (answer text, artifacts, previews). */
const RAIL_KINDS: ReadonlySet<BlockKind> = new Set([
  "thinking",
  "tool",
  "context",
  "compaction_progress",
  "review",
  "host_command",
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
export function Rail(props: {
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
export function fullWidthTop(top?: TopSpacing): string | undefined {
  return top && top !== "none" ? "mt-3" : undefined;
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

/** Render one block group by kind. Host commands arrive as a group (consecutive blocks
 *  batched) so their cards keep one shared decision.
 *
 *  Approvals and questions have no case here: a parked run is answered in the dock that
 *  takes over the composer, not on the rail (`ParkDock`, and `groupBlocks`'s `DOCKED`). */
export function BlockRow(
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
      <Match when={g().kind === "context"}>
        {/* On the rail, because it happened in the turn's sequence — but never `active`:
            the rail's light means "this is running now", and an injection is a settled
            fact the moment it exists. Lighting it would spend the one signal the
            interface delivers in light on something with no duration. */}
        <Rail top={props.top}>
          <ContextInjectionCard
            injection={(g().blocks[0] as ContextBlock).injection}
            open={props.forceOpen}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "compaction_progress"}>
        {/* On the rail, because the turn genuinely stopped here — and `active` while the
            summarizer runs, unlike the injection above: this row is the one chassis
            event that has duration, which is the whole reason it is on screen. The card
            carries the same state as a throbber, so the rail's light and the glyph say
            it from two distances. */}
        {(() => {
          const c = () => (g().blocks[0] as CompactionProgressBlock).compaction;
          return (
            <Rail active={!c().done} top={props.top}>
              <CompactionProgressCard compaction={c()} />
            </Rail>
          );
        })()}
      </Match>
      <Match when={g().kind === "review"}>
        {/* On the rail, because it happened in the turn's sequence, and never `active`:
            the rail's light means "the model is doing this now", and a review is the
            chassis answering for the operator — the opposite kind of event. */}
        <Rail top={props.top}>
          <ReviewCard
            review={(g().blocks[0] as ReviewBlock).review}
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
    </Switch>
  );
}

/** The top spacing for the item at `index`: nothing for the first, a connected
 *  rail when this and the previous row are both rail blocks, otherwise a plain
 *  gap (run boundary). */
export function topSpacing(items: LayoutItem[], index: number): TopSpacing {
  if (index === 0) return "none";
  const isRail = (it: LayoutItem) =>
    it.type === "group" && RAIL_KINDS.has(it.group.kind);
  return isRail(items[index]) && isRail(items[index - 1]) ? "connect" : "gap";
}
