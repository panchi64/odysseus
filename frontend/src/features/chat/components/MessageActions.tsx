import { Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  Icon,
  Menu,
  Text,
  copyToClipboard,
  toast,
  type MenuItem,
} from "~/ui";
import type { ChatMessage } from "../model";
import {
  answerText,
  assembleTranscript,
  hasReasoning,
  reasoningText,
} from "../blocks";
import { createDocument } from "~/features/documents/data";

/** The turn's plain-text content, whichever role — a user turn's content lives
 *  in `content`, an assistant turn's in its text blocks. */
function messageText(m: ChatMessage): string {
  return m.role === "assistant" ? answerText(m.blocks) : m.content;
}

/** A readable document title from a turn's opening line, capped so it stays a
 *  title rather than a wrapped paragraph. */
function titleFromText(text: string): string {
  const firstLine = text.trim().split("\n", 1)[0]?.trim() ?? "";
  return firstLine.slice(0, 60) || "Untitled";
}

/** Hover/focus-revealed action row for a chat turn. Lives inside a `group`
 *  wrapper in the parent turn and surfaces on hover or keyboard focus
 *  (`focus-within`), so it stays reachable without a pointer. */
export function MessageActions(props: {
  message: ChatMessage;
  /** Re-answer an assistant turn with the current model selection. */
  onRegenerate?: () => void;
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
  const navigate = useNavigate();

  async function saveToDocument() {
    const text = messageText(m());
    if (!text.trim()) return;
    try {
      const id = await createDocument(titleFromText(text), text);
      toast.success("Saved to document", {
        action: { label: "OPEN", onClick: () => navigate(`/documents/${id}`) },
      });
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Unable to save the document.",
      );
    }
  }

  return (
    <div class="flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      {/* Lead with the turn's primary action: edit for the operator's own
          message, regenerate/rewind for the assistant's answer. */}
      <Show when={!isAssistant() && props.onEdit}>
        <Button
          variant="ghost"
          size="sm"
          leading="pen"
          aria-label="Edit message"
          onClick={() => props.onEdit?.()}
        >
          EDIT
        </Button>
      </Show>
      <Show when={isAssistant() && props.onRegenerate}>
        <Button
          variant="ghost"
          size="sm"
          leading="refresh"
          aria-label="Regenerate answer"
          onClick={() => props.onRegenerate?.()}
        >
          REGENERATE
        </Button>
      </Show>
      <Show when={isAssistant() && props.onRewind}>
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-up"
          aria-label="Rewind to here"
          onClick={() => props.onRewind?.()}
        >
          REWIND
        </Button>
      </Show>

      {/* Both roles: copy (answer / full message / reasoning). */}
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
                onSelect: () =>
                  copyToClipboard(answerText(m().blocks), "Answer"),
              },
              {
                label: "COPY MESSAGE",
                icon: "layers",
                onSelect: () =>
                  copyToClipboard(assembleTranscript(m().blocks), "Message"),
              },
              ...(hasReasoning(m().blocks)
                ? [
                    {
                      label: "COPY REASONING",
                      icon: "note",
                      onSelect: () =>
                        copyToClipboard(reasoningText(m().blocks), "Reasoning"),
                    } satisfies MenuItem,
                  ]
                : []),
            ] satisfies MenuItem[]
          }
        />
      </Show>

      {/* Both roles: pin, save-to-document, delete. */}
      <Button
        variant="ghost"
        size="sm"
        leading="pin"
        aria-label={m().pinned ? "Unpin message" : "Pin message"}
        onClick={() => props.onTogglePin?.()}
      >
        {m().pinned ? "PINNED" : "PIN"}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        leading="note"
        aria-label="Save to document"
        onClick={() => void saveToDocument()}
      >
        SAVE TO DOCUMENT
      </Button>
      <Show when={props.onDelete}>
        <Button
          variant="danger"
          size="sm"
          leading="trash"
          aria-label="Delete message"
          onClick={() => props.onDelete?.()}
        >
          DELETE
        </Button>
      </Show>

      {props.children}
    </div>
  );
}
