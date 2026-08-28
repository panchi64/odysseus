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

/** The one hover/focus reveal in a turn. Metadata and actions surface together on
 *  the same gesture — `opacity`, not `hidden`, so nothing reflows when they appear
 *  and `focus-within` keeps every control reachable from the keyboard. Exported so
 *  the turn's own model/time line uses this mechanism rather than a second one. */
export const TURN_REVEAL_CLASS =
  "opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100";

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

/** Hover/focus-revealed action row for a chat turn: COPY, and everything else
 *  behind one overflow menu.
 *
 *  Seven labelled buttons per turn made every exchange read as a toolbar with a
 *  message attached, and the transcript is the thing being read. COPY stays out
 *  because it is the action reached most often and costs nothing to leave in
 *  reach; the rest — edit, regenerate, rewind, pin, save, delete — are deliberate
 *  acts that survive one click of indirection. Nothing was removed. */
export function MessageActions(props: {
  message: ChatMessage;
  /** Re-answer an assistant turn with the current model selection. */
  onRegenerate?: () => void;
  /** Enter edit-in-place on a user turn. */
  onEdit?: () => void;
  /** Rewind the thread to (and including) this turn. */
  onRewind?: () => void;
  /** Open a new conversation carrying history up to this turn. */
  onFork?: () => void;
  /** Delete this turn and everything after it. */
  onDelete?: () => void;
  /** Pin/unpin this turn (backend-owned flag). */
  onTogglePin?: () => void;
  /** Turn-specific entries appended to the overflow menu (e.g. expand-all). */
  extraItems?: MenuItem[];
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
        action: { label: "Open", onClick: () => navigate(`/documents/${id}`) },
      });
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Unable to save the document.",
      );
    }
  }

  const overflowItems = (): MenuItem[] => [
    // Lead with the turn's primary act: edit for the operator's own message,
    // regenerate/rewind for the assistant's answer.
    ...(!isAssistant() && props.onEdit
      ? [
          {
            label: "Edit",
            icon: "pen",
            onSelect: () => props.onEdit?.(),
          } satisfies MenuItem,
        ]
      : []),
    ...(isAssistant() && props.onRegenerate
      ? [
          {
            label: "Regenerate",
            icon: "refresh",
            onSelect: () => props.onRegenerate?.(),
          } satisfies MenuItem,
        ]
      : []),
    ...(isAssistant() && props.onRewind
      ? [
          {
            label: "Rewind to here",
            icon: "chevron-up",
            onSelect: () => props.onRewind?.(),
          } satisfies MenuItem,
        ]
      : []),
    // Distinct from REWIND, which moves this thread's tip: a fork leaves this
    // conversation exactly as it is and opens a second one carrying the history
    // up to here, so a promising tangent doesn't cost the thread it came from.
    ...(props.onFork
      ? [
          {
            label: "Fork from here",
            icon: "branch",
            onSelect: () => props.onFork?.(),
          } satisfies MenuItem,
        ]
      : []),
    {
      label: m().pinned ? "Unpin" : "PIN",
      icon: "pin",
      onSelect: () => props.onTogglePin?.(),
    },
    {
      label: "Save to document",
      icon: "note",
      onSelect: () => void saveToDocument(),
    },
    ...(props.extraItems ?? []),
    ...(props.onDelete
      ? [
          {
            label: "Delete",
            icon: "trash",
            danger: true,
            onSelect: () => props.onDelete?.(),
          } satisfies MenuItem,
        ]
      : []),
  ];

  return (
    <div class={`flex items-center gap-1 ${TURN_REVEAL_CLASS}`}>
      {/* Copy: one button on a user turn, a small menu on an assistant turn,
          where "the answer", "the whole turn", and "the reasoning" are different
          things to put on the clipboard. */}
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
            Copy
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
                Copy
              </Text>
            </span>
          }
          items={
            [
              {
                label: "Copy answer",
                icon: "copy",
                onSelect: () =>
                  copyToClipboard(answerText(m().blocks), "Answer"),
              },
              {
                label: "Copy message",
                icon: "layers",
                onSelect: () =>
                  copyToClipboard(assembleTranscript(m().blocks), "Message"),
              },
              ...(hasReasoning(m().blocks)
                ? [
                    {
                      label: "Copy reasoning",
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

      <Menu
        align="left"
        trigger={
          <Button variant="ghost" size="sm" aria-label="Turn actions">
            ···
          </Button>
        }
        items={overflowItems()}
      />
    </div>
  );
}
