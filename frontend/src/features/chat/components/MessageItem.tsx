import { For, Show, type JSX } from "solid-js";
import { Caret, Markdown, Stack, Text } from "~/ui";
import { relativeTime } from "~/lib/format";
import type { ApprovalDecision, ChatMessage } from "../model";
import { ApprovalCard } from "./ApprovalCard";
import { ArtifactViewer } from "./ArtifactViewer";
import { HostCommandCard } from "./HostCommandCard";
import { PreviewPane } from "./PreviewPane";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCallCard } from "./ToolCallCard";

export interface MessageItemProps {
  message: ChatMessage;
  /** Decide a turn's pending approvals (wired from the stream controller). */
  onResolveApproval?: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => void | Promise<void>;
  /** Decide a turn's pending host-command approvals (terminal blocks). */
  onResolveHostCommands?: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => void | Promise<void>;
}

/** A single chat turn. User turns fill the row with a distinct `surface`
 *  background and right-aligned content; assistant turns sit on the base
 *  background with reasoning, tool calls, then a markdown-formatted answer and a
 *  streaming caret while in flight. */
export function MessageItem(props: MessageItemProps): JSX.Element {
  return (
    <Show
      when={props.message.role === "user"}
      fallback={
        <AssistantTurn
          message={props.message}
          onResolveApproval={props.onResolveApproval}
          onResolveHostCommands={props.onResolveHostCommands}
        />
      }
    >
      <UserTurn message={props.message} />
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

function AssistantTurn(props: {
  message: ChatMessage;
  onResolveApproval?: MessageItemProps["onResolveApproval"];
  onResolveHostCommands?: MessageItemProps["onResolveHostCommands"];
}): JSX.Element {
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

        <Show when={m().hostCommands?.length}>
          <HostCommandCard
            commands={m().hostCommands!}
            onSubmit={(decisions) =>
              props.onResolveHostCommands?.(m().id, decisions)
            }
          />
        </Show>

        <Show when={m().approvals?.length}>
          <ApprovalCard
            approvals={m().approvals!}
            onSubmit={(decisions) =>
              props.onResolveApproval?.(m().id, decisions)
            }
          />
        </Show>

        <Show when={m().artifacts?.length}>
          <Stack gap={2}>
            <For each={m().artifacts}>
              {(artifact) => <ArtifactViewer artifact={artifact} />}
            </For>
          </Stack>
        </Show>

        <Show when={m().preview}>
          {(preview) => <PreviewPane preview={preview()} />}
        </Show>

        <Show
          when={m().content}
          fallback={
            <Show when={m().streaming}>
              <Text variant="body" tone="dim">
                <Caret />
              </Text>
            </Show>
          }
        >
          <div>
            <Markdown class="inline">{m().content}</Markdown>
            <Show when={m().streaming}>
              {" "}
              <Caret class="text-bright" />
            </Show>
          </div>
        </Show>
      </Stack>
    </div>
  );
}
