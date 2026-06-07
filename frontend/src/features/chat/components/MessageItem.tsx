import { For, Show, type JSX } from "solid-js";
import { Markdown, Stack, Text } from "~/ui";
import { relativeTime } from "~/lib/format";
import type { ChatMessage } from "../model";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";

/** A single chat turn. User turns fill the row with a distinct `surface`
 *  background and right-aligned content; assistant turns sit on the base
 *  background with reasoning, tool calls, then a markdown-formatted answer and a
 *  streaming caret while in flight. */
export function MessageItem(props: { message: ChatMessage }): JSX.Element {
  const m = () => props.message;
  return (
    <Show when={m().role === "user"} fallback={<AssistantTurn message={m()} />}>
      <UserTurn message={m()} />
    </Show>
  );
}

function UserTurn(props: { message: ChatMessage }): JSX.Element {
  return (
    <div class="flex flex-col items-end gap-1 border-b border-line bg-surface px-4 py-3">
      <div class="flex items-center gap-2">
        <Text variant="micro" tone="dim">
          {relativeTime(props.message.createdAt)}
        </Text>
        <Text variant="label" tone="default">
          OPERATOR
        </Text>
      </div>
      <Text
        variant="body"
        tone="bright"
        class="max-w-[80%] whitespace-pre-wrap break-words text-right"
      >
        {props.message.content}
      </Text>
    </div>
  );
}

function AssistantTurn(props: { message: ChatMessage }): JSX.Element {
  const m = () => props.message;
  return (
    <div class="border-b border-line px-4 py-4">
      <div class="mb-2 flex items-center gap-2">
        <Text variant="label" tone="nominal">
          {m().model ?? "ASSISTANT"}
        </Text>
        <Text variant="micro" tone="dim">
          {relativeTime(m().createdAt)}
        </Text>
      </div>

      <Stack gap={2}>
        <Show when={m().reasoning}>
          <ReasoningBlock reasoning={m().reasoning!} />
        </Show>

        <Show when={m().tools?.length}>
          <Stack gap={1}>
            <For each={m().tools}>{(tool) => <ToolCallCard tool={tool} />}</For>
          </Stack>
        </Show>

        <Show
          when={m().content}
          fallback={
            <Show when={m().streaming}>
              <Text variant="body" tone="dim">
                <span class="ody-caret">▋</span>
              </Text>
            </Show>
          }
        >
          <div>
            <Markdown class="inline">{m().content}</Markdown>
            <Show when={m().streaming}>
              <span class="ody-caret text-bright"> ▋</span>
            </Show>
          </div>
        </Show>
      </Stack>
    </div>
  );
}
