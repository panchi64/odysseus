import { Show, createSignal, type JSX } from "solid-js";
import { Icon, StatusFlag, Text, type Status } from "~/ui";
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

/** Inline record of a single tool invocation inside an assistant message. */
export function ToolCallCard(props: { tool: ToolInvocation }): JSX.Element {
  const [open, setOpen] = createSignal(false);
  const flag = () => statusFlag[props.tool.status];
  return (
    <div class="border border-line bg-bg">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        class="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left transition-colors hover:bg-raised"
      >
        <span class="flex min-w-0 items-center gap-2">
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
        </span>
        <span class="flex shrink-0 items-center gap-2">
          <Show when={props.tool.elapsedMs !== undefined}>
            <Text variant="micro" tone="dim">
              {num(props.tool.elapsedMs! / 1000, 2)}S
            </Text>
          </Show>
          <StatusFlag status={flag().status}>{flag().label}</StatusFlag>
        </span>
      </button>
      <Show when={open() && props.tool.result}>
        <div class="border-t border-line px-2 py-1.5">
          <Text
            variant="micro"
            tone="dim"
            class="whitespace-pre-wrap break-words"
          >
            {props.tool.result}
          </Text>
        </div>
      </Show>
    </div>
  );
}
