import { Show, type JSX } from "solid-js";
import {
  Button,
  Icon,
  Menu,
  Text,
  Tooltip,
  copyToClipboard,
  type MenuItem,
} from "~/ui";
import { modelGroups } from "~/lib/stores/models";
import type { ChatMessage } from "../model";

/** Assemble a message's full record — reasoning, each tool call as
 *  `name(args) -> result/error`, then the answer — into one plain-text block for
 *  "COPY MESSAGE". */
function assembleMessage(m: ChatMessage): string {
  const parts: string[] = [];
  if (m.reasoning) parts.push(`REASONING\n${m.reasoning}`);
  for (const t of m.tools ?? []) {
    const outcome = t.error ? `error: ${t.error}` : (t.result ?? "");
    parts.push(`${t.name}(${t.args}) -> ${outcome}`);
  }
  if (m.content) parts.push(m.content);
  return parts.join("\n\n");
}

/** Hover/focus-revealed action row for a chat turn. Lives inside a `group`
 *  wrapper in the parent turn and surfaces on hover or keyboard focus
 *  (`focus-within`), so it stays reachable without a pointer. */
export function MessageActions(props: {
  message: ChatMessage;
  /** Re-answer an assistant turn (current selection, or a chosen model). */
  onRegenerate?: (model?: { endpointId: string; model: string }) => void;
  /** Enter edit-in-place on a user turn. */
  onEdit?: () => void;
  /** Rewind the thread to (and including) this turn. */
  onRewind?: () => void;
  /** Delete this turn and everything after it. */
  onDelete?: () => void;
  /** Pin/unpin this turn (backend-owned flag). */
  onTogglePin?: () => void;
  /** Extra controls (e.g. expand-all) rendered alongside the copy affordance. */
  children?: JSX.Element;
}): JSX.Element {
  const m = () => props.message;
  const isAssistant = () => m().role === "assistant";

  // A "Regenerate with <model>" picker is offered when the catalog has more than
  // one choice; otherwise REGENERATE is a plain button using the current pick.
  const regenItems = (): MenuItem[] =>
    modelGroups().flatMap((g) =>
      g.choices.map((c) => ({
        label: `↻ ${c.model}`,
        icon: "refresh" as const,
        onSelect: () =>
          props.onRegenerate?.({ endpointId: c.endpointId, model: c.model }),
      })),
    );
  const hasModelChoices = () => regenItems().length > 1;

  return (
    <div class="flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      <Show
        when={isAssistant()}
        fallback={
          <Button
            variant="ghost"
            size="sm"
            leading="copy"
            aria-label="Copy message"
            onClick={() => copyToClipboard(m().content, "Answer")}
          >
            COPY
          </Button>
        }
      >
        <Menu
          align="left"
          trigger={
            <span
              class="inline-flex h-6 items-center gap-1 rounded-ctl border border-transparent px-2 text-dim transition-colors hover:text-bright"
              aria-label="Copy message"
            >
              <Icon name="copy" size={12} />
              <Text variant="label" tone="dim">
                COPY
              </Text>
            </span>
          }
          items={
            [
              {
                label: "COPY ANSWER",
                icon: "copy",
                onSelect: () => copyToClipboard(m().content, "Answer"),
              },
              {
                label: "COPY MESSAGE",
                icon: "layers",
                onSelect: () =>
                  copyToClipboard(assembleMessage(m()), "Message"),
              },
              ...(m().reasoning
                ? [
                    {
                      label: "COPY REASONING",
                      icon: "note",
                      onSelect: () =>
                        copyToClipboard(m().reasoning!, "Reasoning"),
                    } satisfies MenuItem,
                  ]
                : []),
            ] satisfies MenuItem[]
          }
        />
      </Show>

      {/* User turns: edit-in-place. */}
      <Show when={!isAssistant() && props.onEdit}>
        <Tooltip label="EDIT">
          <Button
            variant="ghost"
            size="sm"
            leading="pen"
            aria-label="Edit message"
            onClick={() => props.onEdit?.()}
          >
            EDIT
          </Button>
        </Tooltip>
      </Show>

      {/* Assistant turns: regenerate (with optional model override) + rewind. */}
      <Show when={isAssistant() && props.onRegenerate}>
        <Show
          when={hasModelChoices()}
          fallback={
            <Tooltip label="REGENERATE">
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                aria-label="Regenerate answer"
                onClick={() => props.onRegenerate?.()}
              >
                REGENERATE
              </Button>
            </Tooltip>
          }
        >
          <Menu
            align="left"
            trigger={
              <span
                class="inline-flex h-6 items-center gap-1 rounded-ctl border border-transparent px-2 text-dim transition-colors hover:text-bright"
                aria-label="Regenerate answer"
              >
                <Icon name="refresh" size={12} />
                <Text variant="label" tone="dim">
                  REGENERATE
                </Text>
              </span>
            }
            items={[
              {
                label: "↻ Current model",
                icon: "refresh",
                onSelect: () => props.onRegenerate?.(),
              },
              ...regenItems(),
            ]}
          />
        </Show>
      </Show>
      <Show when={isAssistant() && props.onRewind}>
        <Tooltip label="REWIND">
          <Button
            variant="ghost"
            size="sm"
            leading="chevron-up"
            aria-label="Rewind to here"
            onClick={() => props.onRewind?.()}
          >
            REWIND
          </Button>
        </Tooltip>
      </Show>

      {/* Both roles: pin, save-to-notes (Phase 2), delete. */}
      <Tooltip label={m().pinned ? "UNPIN" : "PIN"}>
        <Button
          variant="ghost"
          size="sm"
          leading="pin"
          aria-label={m().pinned ? "Unpin message" : "Pin message"}
          onClick={() => props.onTogglePin?.()}
        >
          {m().pinned ? "PINNED" : "PIN"}
        </Button>
      </Tooltip>
      <Tooltip label="Available in Phase 2">
        <Button variant="ghost" size="sm" leading="note" disabled>
          SAVE TO NOTES
        </Button>
      </Tooltip>
      <Show when={props.onDelete}>
        <Tooltip label="DELETE">
          <Button
            variant="danger"
            size="sm"
            leading="trash"
            aria-label="Delete message"
            onClick={() => props.onDelete?.()}
          >
            DELETE
          </Button>
        </Tooltip>
      </Show>

      {props.children}
    </div>
  );
}
