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
import { Caret, Icon, Markdown, Text, cx } from "~/ui";
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
  peekLatestTool,
  planTurnLayout,
  type BlockGroup,
  type LayoutItem,
} from "../blocks";
import { LIVE_KEY, snapshotKey, versionIcon } from "../viewport";
import { ApprovalCard } from "./ApprovalCard";
import { HostCommandCard } from "./HostCommandCard";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";
import { ViewChip } from "./ViewChip";

type Resolve = (decisions: ApprovalDecision[]) => void | Promise<void>;
const noop: Resolve = () => {};

interface RowHandlers {
  onResolveApproval?: Resolve;
  onResolveHostCommands?: Resolve;
  /** Open a View item (a version or the live head) in the side viewport, by key. */
  onOpenInView?: (key: string) => void;
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

/** A passage of the answer — full-width and bright. The active, still-streaming
 *  passage carries the caret and defers code-copy enhancement until it settles. */
function AnswerText(props: {
  text: string;
  active?: boolean;
  streaming?: boolean;
}): JSX.Element {
  const live = () => Boolean(props.active && props.streaming);
  return (
    <div>
      <Markdown class="inline" copyCode={!live()}>
        {props.text}
      </Markdown>
      <Show when={live()}>
        {" "}
        <Caret class="text-bright" />
      </Show>
    </div>
  );
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
          return (
            <div class={fullWidthTop(props.top)}>
              <ViewChip
                icon={versionIcon(b.previewKind)}
                label={b.title || "Version"}
                onOpen={() => props.onOpenInView?.(snapshotKey(b.snapshotId))}
              />
            </div>
          );
        })()}
      </Match>
      <Match when={g().kind === "view_live"}>
        {(() => {
          const live = (g().blocks[0] as ViewLiveBlock).live;
          return (
            <div class={fullWidthTop(props.top)}>
              <ViewChip
                icon="play"
                label={live.title || "Live view"}
                live
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
      <button
        type="button"
        onClick={() => props.onToggle()}
        class="flex w-full items-center gap-2 text-left text-dim transition-colors hover:text-text"
      >
        <Icon name={props.open ? "chevron-down" : "chevron-right"} size={12} />
        <Text variant="label" tone="dim">
          WORK LOG · {props.groups.length}{" "}
          {props.groups.length === 1 ? "STEP" : "STEPS"}
        </Text>
        <Show when={!props.open && peek()}>
          {(p) => (
            <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
              {p().name}
              {p().rationale ? ` — ${p().rationale}` : ""}
            </Text>
          )}
        </Show>
      </button>
      <Show when={props.open}>
        {/* Every folded group is a rail block, so they connect into one line. */}
        <div class="mt-2">
          <For each={props.groups}>
            {(group, i) => (
              <BlockRow
                group={group}
                top={i() === 0 ? "none" : "connect"}
                forceOpen={props.forceOpen}
                onResolveApproval={props.onResolveApproval}
                onResolveHostCommands={props.onResolveHostCommands}
              />
            )}
          </For>
        </div>
      </Show>
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
  } & RowHandlers,
): JSX.Element {
  // Memoized so a text/thinking delta (which doesn't change block *structure*)
  // doesn't re-group/re-plan, and so `activeId` reuses the same grouping rather
  // than recomputing it — one structural pass per real change, not per token.
  const groups = createMemo(() => groupBlocks(props.blocks));
  const layout = createMemo(() =>
    planTurnLayout(groups(), { streaming: props.streaming }),
  );
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
            />
          )
        }
      </For>
    </div>
  );
}
