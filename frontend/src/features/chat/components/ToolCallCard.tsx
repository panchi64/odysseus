import {
  Show,
  createEffect,
  createMemo,
  createSignal,
  type JSX,
} from "solid-js";
import {
  Frames,
  Icon,
  StatusFlag,
  Text,
  copyToClipboard,
  type Status,
} from "~/ui";
import { num } from "~/lib/format";
import type { ToolInvocation } from "../model";
import { toolPresentation } from "../toolPresentation";

const statusFlag: Record<
  ToolInvocation["status"],
  { status: Status; label: string }
> = {
  running: { status: "info", label: "Running" },
  ok: { status: "nominal", label: "OK" },
  error: { status: "alert", label: "Error" },
};

/** The family glyph carries the call's state as well as its kind, so a column of
 *  rows reads at a glance without parsing the flag at the far right. */
const iconTone: Record<ToolInvocation["status"], string> = {
  running: "text-info",
  ok: "text-dim",
  error: "text-alert",
};

/** The `·` between segments of one row. Quiet enough to read as punctuation
 *  rather than as another value. */
function Sep(): JSX.Element {
  return (
    <Text variant="micro" tone="dim" class="shrink-0 opacity-50 select-none">
      ·
    </Text>
  );
}

/** Inline record of a single tool invocation inside an assistant message.
 *
 *  The collapsed row is `glyph · Label · what it was about · what came back` —
 *  the namespaced registry name (`files_read_file`) and the full argument dump
 *  move into the expanded body, where an operator who wants them is already
 *  looking. A turn is a dozen of these rows, and the row has to be scannable
 *  without being read.
 *
 *  `open` makes expand/collapse controlled (expand-all/collapse-all); when
 *  undefined the card keeps its default behavior (auto-open on error). */
export function ToolCallCard(props: {
  tool: ToolInvocation;
  open?: boolean;
}): JSX.Element {
  // Auto-expand error cards so the reason is immediately visible.
  const [open, setOpen] = createSignal(props.tool.status === "error");
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
  });
  const flag = () => statusFlag[props.tool.status];
  const shown = createMemo(() => toolPresentation(props.tool.name));
  // The salient argument when one stood out, else the full summary — never
  // nothing, so a row is always about something.
  const detail = () => props.tool.detail ?? props.tool.args;
  // Copy the most useful payload available: result, else error, else the args.
  const copyTool = (e: MouseEvent): void => {
    e.stopPropagation();
    copyToClipboard(
      props.tool.result ?? props.tool.error ?? props.tool.args,
      "Tool result",
    );
  };
  return (
    <div class="group/tool overflow-hidden rounded-panel bg-surface shadow-1">
      <div class="flex w-full items-center justify-between gap-2 pr-1.5 transition-colors hover:bg-raised">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          class="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left"
          title={props.tool.name}
        >
          <Icon
            name={open() ? "chevron-down" : "chevron-right"}
            size={12}
            class="text-dim"
          />
          <Icon
            name={shown().icon}
            size={12}
            class={iconTone[props.tool.status]}
          />
          {/* Every text segment truncates rather than holding its width. A
              `shrink-0` segment inside this `min-w-0 flex-1` button escapes the
              button's box on a narrow viewport and paints over the status
              cluster to its right; `truncate`'s `overflow:hidden` is what lets a
              flex item shrink below its content at all. Flex shrinks the longest
              segment hardest, so the label — the shortest — survives in practice
              without being pinned. */}
          <Text variant="label" tone="bright" class="min-w-0 truncate">
            {shown().label}
          </Text>
          <Show
            when={props.tool.status === "running" && props.tool.progress}
            fallback={
              <Show when={detail()}>
                <Sep />
                <Text variant="micro" tone="dim" class="min-w-0 truncate">
                  {detail()}
                </Text>
              </Show>
            }
          >
            <Sep />
            <span class="flex min-w-0 items-center gap-1.5">
              <Frames class="text-info" />
              <Text variant="micro" tone="info" class="truncate">
                {props.tool.progress}
              </Text>
            </span>
          </Show>
          <Show when={props.tool.status === "ok" && props.tool.outcome}>
            <Sep />
            <Text variant="micro" tone="default" class="min-w-0 truncate">
              {props.tool.outcome}
            </Text>
          </Show>
        </button>
        <span class="flex shrink-0 items-center gap-2">
          <Show when={props.tool.elapsedMs !== undefined}>
            <Text variant="micro" tone="dim">
              {num(props.tool.elapsedMs! / 1000, 2)}S
            </Text>
          </Show>
          <StatusFlag status={flag().status}>{flag().label}</StatusFlag>
          <button
            type="button"
            aria-label="Copy tool result"
            onClick={copyTool}
            class="text-dim opacity-0 transition-opacity hover:text-bright focus:opacity-100 group-hover/tool:opacity-100"
          >
            <Icon name="copy" size={12} />
          </button>
        </span>
      </div>
      <Show when={open()}>
        <div class="flex flex-col gap-1 px-2 py-1.5">
          {/* The registry name and every argument — what the collapsed row trades
              away for scannability, restored the moment the operator asks.
              Height-capped and scrollable: `formatArgs` does not truncate, and a
              `code_execute` call's arguments ARE its script, which would
              otherwise push the result the operator opened the card for off the
              bottom of the screen. */}
          <Text
            as="div"
            variant="micro"
            tone="dim"
            class="max-h-24 overflow-y-auto break-words"
          >
            <span class="text-text">{props.tool.name}</span>
            {props.tool.args ? ` ${props.tool.args}` : ""}
          </Text>
          <Show
            when={props.tool.status === "error" && props.tool.error}
            fallback={
              <Show when={props.tool.result}>
                <Text
                  variant="micro"
                  tone="dim"
                  class="whitespace-pre-wrap break-words"
                >
                  {props.tool.result}
                </Text>
              </Show>
            }
          >
            <Text
              variant="micro"
              tone="alert"
              class="whitespace-pre-wrap break-words"
            >
              {props.tool.error}
            </Text>
          </Show>
          <Show
            when={
              props.tool.status === "error" &&
              !props.tool.error &&
              !props.tool.result
            }
          >
            <Text variant="micro" tone="alert">
              Tool failed with no additional detail.
            </Text>
          </Show>
        </div>
      </Show>
    </div>
  );
}
