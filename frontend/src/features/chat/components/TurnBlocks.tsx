import {
  For,
  Match,
  Show,
  Switch,
  createEffect,
  createMemo,
  createSignal,
  type JSX,
} from "solid-js";
import { Caret, Icon, Markdown, Stack, Text, cx } from "~/ui";
import type {
  ApprovalBlock,
  ApprovalDecision,
  ArtifactBlock,
  AssistantBlock,
  HostCommandBlock,
  PreviewBlock,
  TextBlock,
  ThinkingBlock,
  ToolBlock,
} from "../model";
import {
  groupBlocks,
  peekLatestTool,
  planTurnLayout,
  type BlockGroup,
} from "../blocks";
import { ApprovalCard } from "./ApprovalCard";
import { ArtifactViewer } from "./ArtifactViewer";
import { HostCommandCard } from "./HostCommandCard";
import { PreviewPane } from "./PreviewPane";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";

type Resolve = (decisions: ApprovalDecision[]) => void | Promise<void>;
const noop: Resolve = () => {};

interface RowHandlers {
  onResolveApproval?: Resolve;
  onResolveHostCommands?: Resolve;
}

/** The left rail that turns a stack of process blocks into a legible, ordered
 *  timeline. A 1px hairline — the workhorse divider that enforces structure
 *  (§2) — coloured to mark the live block (brightness/hue, not width, so the
 *  block never reflows when it goes active, §1). Answer/artifact/preview render
 *  full-width (results lead; work recedes). */
function Rail(props: { active?: boolean; children: JSX.Element }): JSX.Element {
  return (
    <div
      class={cx(
        "border-l pl-3 transition-colors",
        props.active ? "border-info" : "border-line",
      )}
    >
      {props.children}
    </div>
  );
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
  } & RowHandlers,
): JSX.Element {
  const g = () => props.group;
  return (
    <Switch>
      <Match when={g().kind === "text"}>
        <AnswerText
          text={(g().blocks[0] as TextBlock).text}
          active={props.active}
          streaming={props.streaming}
        />
      </Match>
      <Match when={g().kind === "artifact"}>
        <ArtifactViewer artifact={(g().blocks[0] as ArtifactBlock).artifact} />
      </Match>
      <Match when={g().kind === "preview"}>
        <PreviewPane preview={(g().blocks[0] as PreviewBlock).preview} />
      </Match>
      <Match when={g().kind === "thinking"}>
        <Rail active={props.active}>
          <ReasoningBlock
            reasoning={(g().blocks[0] as ThinkingBlock).text}
            open={props.forceOpen}
            active={props.active}
            streaming={props.streaming}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "tool"}>
        <Rail active={props.active}>
          <ToolCallCard
            tool={(g().blocks[0] as ToolBlock).tool}
            open={props.forceOpen}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "host_command"}>
        <Rail active={props.active}>
          <HostCommandCard
            commands={(g().blocks as HostCommandBlock[]).map((b) => b.command)}
            open={props.forceOpen}
            onSubmit={props.onResolveHostCommands ?? noop}
          />
        </Rail>
      </Match>
      <Match when={g().kind === "approval"}>
        <Rail active={props.active}>
          <ApprovalCard
            approvals={(g().blocks as ApprovalBlock[]).map((b) => b.approval)}
            onSubmit={props.onResolveApproval ?? noop}
          />
        </Rail>
      </Match>
    </Switch>
  );
}

/** The compacted work log: a leading run of process blocks folded into one
 *  accordion that peeks the latest call + its rationale, so a long turn doesn't
 *  bury the screen. Expanding restores the full ordered run. */
function WorkLogAccordion(
  props: { groups: BlockGroup[]; forceOpen?: boolean } & RowHandlers,
): JSX.Element {
  const [open, setOpen] = createSignal(false);
  createEffect(() => {
    if (props.forceOpen !== undefined) setOpen(props.forceOpen);
  });
  const peek = createMemo(() => peekLatestTool(props.groups));

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        class="flex w-full items-center gap-2 text-left text-dim transition-colors hover:text-text"
      >
        <Icon name={open() ? "chevron-down" : "chevron-right"} size={12} />
        <Text variant="label" tone="dim">
          WORK LOG · {props.groups.length} STEPS
        </Text>
        <Show when={!open() && peek()}>
          {(p) => (
            <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
              {p().name}
              {p().rationale ? ` — ${p().rationale}` : ""}
            </Text>
          )}
        </Show>
      </button>
      <Show when={open()}>
        <Stack gap={3} class="mt-2">
          <For each={props.groups}>
            {(group) => (
              <BlockRow
                group={group}
                forceOpen={props.forceOpen}
                onResolveApproval={props.onResolveApproval}
                onResolveHostCommands={props.onResolveHostCommands}
              />
            )}
          </For>
        </Stack>
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

  return (
    <Stack gap={3}>
      <For each={layout()}>
        {(item) =>
          item.type === "worklog" ? (
            <WorkLogAccordion
              groups={item.groups}
              forceOpen={props.forceOpen}
              onResolveApproval={props.onResolveApproval}
              onResolveHostCommands={props.onResolveHostCommands}
            />
          ) : (
            <BlockRow
              group={item.group}
              active={item.group.id === activeId()}
              streaming={props.streaming}
              forceOpen={props.forceOpen}
              onResolveApproval={props.onResolveApproval}
              onResolveHostCommands={props.onResolveHostCommands}
            />
          )
        }
      </For>
    </Stack>
  );
}
