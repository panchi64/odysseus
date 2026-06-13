import { Show, createSignal, type JSX } from "solid-js";
import { Button, Icon, Stack, Text, Textarea, Tooltip } from "~/ui";
import { relativeTime } from "~/lib/format";
import type { ApprovalDecision, ChatMessage } from "../model";
import { hasLayers as turnHasLayers } from "../blocks";
import { MessageActions } from "./MessageActions";
import { TurnBlocks } from "./TurnBlocks";
import { TurnProgressRail } from "./TurnProgressRail";

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
  /** Re-answer this assistant turn with the current model selection. */
  onRegenerate?: () => void;
  /** Re-ask an edited user turn as a new version. */
  onEditMessage?: (id: string, text: string) => void;
  /** Delete this turn and everything after it. */
  onDelete?: () => void;
  /** Rewind the thread to (and including) this turn. */
  onRewind?: () => void;
  /** Switch this turn to a sibling version (branch). */
  onSwitchVersion?: (id: string, index: number) => void;
  /** Pin/unpin this turn (backend-owned flag). */
  onTogglePin?: () => void;
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
          onRegenerate={props.onRegenerate}
          onDelete={props.onDelete}
          onRewind={props.onRewind}
          onSwitchVersion={props.onSwitchVersion}
          onTogglePin={props.onTogglePin}
        />
      }
    >
      <UserTurn
        message={props.message}
        onEditMessage={props.onEditMessage}
        onDelete={props.onDelete}
        onSwitchVersion={props.onSwitchVersion}
        onTogglePin={props.onTogglePin}
      />
    </Show>
  );
}

/** Compact `‹ n/total ›` cycler shown when a turn has sibling versions. */
function VersionCycler(props: {
  message: ChatMessage;
  onSwitchVersion?: (id: string, index: number) => void;
}): JSX.Element {
  const count = () => props.message.versionCount ?? 1;
  const index = () => props.message.versionIndex ?? 0;
  const go = (next: number) => {
    const clamped = Math.max(0, Math.min(count() - 1, next));
    if (clamped !== index()) props.onSwitchVersion?.(props.message.id, clamped);
  };
  return (
    <Show when={count() > 1}>
      <span class="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-left"
          aria-label="Previous version"
          disabled={index() <= 0}
          onClick={() => go(index() - 1)}
        />
        <Text variant="micro" tone="dim">
          {index() + 1}/{count()}
        </Text>
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-right"
          aria-label="Next version"
          disabled={index() >= count() - 1}
          onClick={() => go(index() + 1)}
        />
      </span>
    </Show>
  );
}

/** Small marker shown in a turn header when the operator has pinned it. */
function PinMarker(props: { message: ChatMessage }): JSX.Element {
  return (
    <Show when={props.message.pinned}>
      <span class="text-nominal" aria-label="Pinned" title="Pinned">
        <Icon name="pin" size={12} />
      </span>
    </Show>
  );
}

function UserTurn(props: {
  message: ChatMessage;
  onEditMessage?: (id: string, text: string) => void;
  onDelete?: () => void;
  onSwitchVersion?: (id: string, index: number) => void;
  onTogglePin?: () => void;
}): JSX.Element {
  const m = () => props.message;
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const startEdit = () => {
    setDraft(m().content);
    setEditing(true);
  };
  const save = () => {
    const text = draft().trim();
    if (text) props.onEditMessage?.(m().id, text);
    setEditing(false);
  };

  return (
    <div class="group flex flex-col items-end gap-1 border-b border-line bg-surface px-4 py-3">
      <div class="flex w-full items-center justify-between gap-2">
        {/* Left: actions reveal on hover. Right: identity + metadata. */}
        <div class="flex items-center gap-2">
          <Show when={!editing()}>
            <MessageActions
              message={m()}
              onEdit={startEdit}
              onDelete={props.onDelete}
              onTogglePin={props.onTogglePin}
            />
          </Show>
        </div>
        <div class="flex items-center gap-2">
          <PinMarker message={m()} />
          <VersionCycler
            message={m()}
            onSwitchVersion={props.onSwitchVersion}
          />
          <Text variant="micro" tone="dim">
            {relativeTime(m().createdAt)}
          </Text>
          <Text variant="label" tone="default">
            OPERATOR
          </Text>
        </div>
      </div>
      <Show
        when={editing()}
        fallback={
          <Text
            variant="body"
            tone="bright"
            class="max-w-[80%] whitespace-pre-wrap break-words text-right"
          >
            {m().content}
          </Text>
        }
      >
        <div class="w-full max-w-[80%]">
          <Textarea
            value={draft()}
            rows={3}
            onInput={(e) => setDraft(e.currentTarget.value)}
            aria-label="Edit message"
          />
          <div class="mt-1 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!draft().trim()}
              onClick={save}
            >
              SAVE
            </Button>
          </div>
        </div>
      </Show>
    </div>
  );
}

function AssistantTurn(props: {
  message: ChatMessage;
  onResolveApproval?: MessageItemProps["onResolveApproval"];
  onResolveHostCommands?: MessageItemProps["onResolveHostCommands"];
  onRegenerate?: MessageItemProps["onRegenerate"];
  onDelete?: MessageItemProps["onDelete"];
  onRewind?: MessageItemProps["onRewind"];
  onSwitchVersion?: MessageItemProps["onSwitchVersion"];
  onTogglePin?: MessageItemProps["onTogglePin"];
}): JSX.Element {
  const m = () => props.message;
  // Tri-state: undefined = each layer keeps its own default; true/false = force
  // every layer open/closed at once. Toggling sets the opposite of its last
  // explicit state (first press expands).
  const [forceOpen, setForceOpen] = createSignal<boolean | undefined>(
    undefined,
  );
  const hasLayers = () => turnHasLayers(m().blocks);
  const toggleAll = () => setForceOpen((v) => !v);

  return (
    <div class="group border-b border-line px-4 py-4">
      <div class="mb-2 flex items-center gap-2">
        <Text variant="label" tone="nominal">
          {m().model ?? "ASSISTANT"}
        </Text>
        <Text variant="micro" tone="dim">
          {relativeTime(m().createdAt)}
        </Text>
        <PinMarker message={m()} />
        <VersionCycler message={m()} onSwitchVersion={props.onSwitchVersion} />
        <span class="ml-auto">
          <MessageActions
            message={m()}
            onRegenerate={props.onRegenerate}
            onRewind={props.onRewind}
            onDelete={props.onDelete}
            onTogglePin={props.onTogglePin}
          >
            <Show when={hasLayers()}>
              <Tooltip label={forceOpen() ? "COLLAPSE ALL" : "EXPAND ALL"}>
                <Button
                  variant="ghost"
                  size="sm"
                  leading="layers"
                  aria-label={forceOpen() ? "Collapse all" : "Expand all"}
                  onClick={toggleAll}
                >
                  {forceOpen() ? "COLLAPSE ALL" : "EXPAND ALL"}
                </Button>
              </Tooltip>
            </Show>
          </MessageActions>
        </span>
      </div>

      <Stack gap={3}>
        {/* What's happening now (streaming) / what it took (settled). */}
        <TurnProgressRail blocks={m().blocks} streaming={m().streaming} />
        {/* The turn's ordered, interleaved blocks — the source of truth. */}
        <TurnBlocks
          blocks={m().blocks}
          streaming={m().streaming}
          forceOpen={forceOpen()}
          onResolveApproval={(decisions) =>
            props.onResolveApproval?.(m().id, decisions)
          }
          onResolveHostCommands={(decisions) =>
            props.onResolveHostCommands?.(m().id, decisions)
          }
        />
      </Stack>
    </div>
  );
}
