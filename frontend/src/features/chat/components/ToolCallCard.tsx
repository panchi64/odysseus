import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { Icon, StatusFlag, Text, copyToClipboard, type Status } from "~/ui";
import { num } from "~/lib/format";
import type { ToolInvocation } from "../model";

const statusFlag: Record<
  ToolInvocation["status"],
  { status: Status; label: string }
> = {
  running: { status: "info", label: "RUNNING" },
  ok: { status: "nominal", label: "OK" },
  error: { status: "alert", label: "ERROR" },
};

/** Inline record of a single tool invocation inside an assistant message.
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
  // Copy the most useful payload available: result, else error, else the args.
  const copyTool = (e: MouseEvent): void => {
    e.stopPropagation();
    copyToClipboard(
      props.tool.result ?? props.tool.error ?? props.tool.args,
      "Tool result",
    );
  };
  return (
    <div class="group/tool border border-line bg-bg">
      <div class="flex w-full items-center justify-between gap-2 pr-1.5 transition-colors hover:bg-raised">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          class="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left"
        >
          <Icon
            name={open() ? "chevron-down" : "chevron-right"}
            size={12}
            class="text-dim"
          />
          <Icon name="plug" size={12} class="text-dim" />
          <Text variant="label" tone="bright" class="truncate">
            {props.tool.name}
          </Text>
          <Text variant="micro" tone="dim" class="truncate">
            {props.tool.args}
          </Text>
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
      <Show when={open() && (props.tool.result || props.tool.error)}>
        <div class="border-t border-line px-2 py-1.5">
          <Show
            when={props.tool.status === "error" && props.tool.error}
            fallback={
              <Text
                variant="micro"
                tone="dim"
                class="whitespace-pre-wrap break-words"
              >
                {props.tool.result}
              </Text>
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
        </div>
      </Show>
      <Show
        when={
          open() &&
          props.tool.status === "error" &&
          !props.tool.error &&
          !props.tool.result
        }
      >
        <div class="border-t border-line px-2 py-1.5">
          <Text variant="micro" tone="alert">
            Tool failed with no additional detail.
          </Text>
        </div>
      </Show>
    </div>
  );
}
