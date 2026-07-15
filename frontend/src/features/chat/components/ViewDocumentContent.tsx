import {
  createEffect,
  createSignal,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { Button, Markdown, markdownBlocks, Textarea, toast } from "~/ui";
import { lineDiff, type DiffResult } from "~/features/documents/diff";
import type { ViewDocumentRef } from "../model";
import { documentKey } from "../viewport";
import {
  consumeAnchor,
  rememberScroll,
  setActiveDownload,
  setViewerDirty,
} from "../viewerPersistence";
import { fontStepMetrics } from "./renderers/fontStep";

/** First line number in the NEW text touched by the diff — the anchor target.
 *  A pure deletion has no line of its own in the new text, so it resolves to
 *  the next line that does (the content right after the cut); a diff with only
 *  trailing deletions (nothing survives after them in the new text) yields
 *  `null`, same as no changes at all. */
function firstChangedNewLine(diff: DiffResult): number | null {
  for (let i = 0; i < diff.lines.length; i++) {
    const line = diff.lines[i];
    if (line.kind === "context") continue;
    if (line.newNo !== undefined) return line.newNo;
    for (let j = i + 1; j < diff.lines.length; j++) {
      const newNo = diff.lines[j].newNo;
      if (newNo !== undefined) return newNo;
    }
    return null;
  }
  return null;
}

/** Which block (0-based, matching `Markdown`'s `streamStable` `data-block-index`)
 *  contains 1-based source line `lineNo`, by walking each block's own line span
 *  cumulatively. Falls back to the last block if `lineNo` runs past the count
 *  (e.g. a trailing-newline miscount) rather than missing the anchor entirely. */
function blockIndexForLine(blocks: string[], lineNo: number): number {
  let cumulative = 0;
  for (let i = 0; i < blocks.length; i++) {
    cumulative += blocks[i].split("\n").length;
    if (lineNo <= cumulative) return i;
  }
  return blocks.length - 1;
}

const ANCHOR_MS = 2000;

/**
 * Renders a document version's **preview** — its markdown + LaTeX body via the shared
 * `Markdown` component (streaming-stable: committed blocks keep their DOM/KaTeX across
 * deltas). The latest committed version is editable inline: an EDIT toggle swaps the
 * rendered prose for a `Textarea` seeded from the body; SAVE relays the new body to the
 * backend (which stamps origin=user and mints a new version) and CANCEL restores. Only
 * the latest committed version is editable — an older version or a still-streaming body
 * shows read-only. The frontend only renders + relays; the backend owns the version it
 * mints.
 *
 * When opened via a chip's "show me what changed" request (`requestAnchor`/
 * `consumeAnchor`), scrolls to and briefly highlights the block containing the first
 * line that differs from the immediately preceding committed version — best-effort,
 * never fatal to the render.
 */
export function ViewDocumentContent(props: {
  document: ViewDocumentRef;
  /** True only for the latest committed version — gates the inline editor. */
  editable: boolean;
  onSave: (documentId: string, body: string) => Promise<void>;
  fontStep?: number;
  /** Accepted for parity with the renderer prop contract — prose always
   *  soft-wraps regardless (it's flowed text, not a fixed-width viewer). */
  softWrap?: boolean;
  /** Prior committed versions of this document, oldest -> newest — used only to
   *  resolve the passage-anchor's diff base (the version immediately before the
   *  one on stage). */
  priorVersions?: ViewDocumentRef[];
}): JSX.Element {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  const itemKey = (): string =>
    documentKey(props.document.documentId, props.document.version);

  const startEdit = (): void => {
    setDraft(props.document.body);
    setEditing(true);
  };
  const cancel = (): void => {
    setEditing(false);
    setViewerDirty(null);
  };
  const save = async (): Promise<void> => {
    setSaving(true);
    try {
      await props.onSave(props.document.documentId, draft());
      toast.success("Document saved");
      setEditing(false);
      setViewerDirty(null);
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Unable to save the document.",
      );
    } finally {
      setSaving(false);
    }
  };

  // Dirty seam: tracks the draft against the saved body while editing; explicit
  // clears above (save/cancel) and below (unmount) cover the rest.
  createEffect(() => {
    setViewerDirty(
      editing() && draft() !== props.document.body ? itemKey() : null,
    );
  });
  onCleanup(() => setViewerDirty(null));

  // Download seam: the current version's body, refreshed whenever the shown
  // version changes (this component remounts per version at the call site, but
  // track props.document defensively rather than assume that).
  createEffect(() => {
    const doc = props.document;
    setActiveDownload({
      name: `${doc.title || "document"}.md`,
      getBlob: async () => new Blob([doc.body], { type: "text/markdown" }),
    });
  });
  onCleanup(() => setActiveDownload(null));

  let scrollRef: HTMLDivElement | undefined;
  let anchorTimer: ReturnType<typeof setTimeout> | undefined;
  onCleanup(() => {
    if (anchorTimer !== undefined) clearTimeout(anchorTimer);
  });

  // Passage anchor: best-effort scroll-to-first-change, requested by a chip open.
  createEffect(() => {
    const doc = props.document;
    const key = itemKey();
    if (!consumeAnchor(key)) return;
    queueMicrotask(() => {
      try {
        const container = scrollRef;
        if (!container) return;
        const priors = props.priorVersions ?? [];
        const previous = priors[priors.length - 1];
        if (!previous) return; // no prior version — nothing to diff against
        const lineNo = firstChangedNewLine(lineDiff(previous.body, doc.body));
        if (lineNo === null) return;
        const blocks = markdownBlocks(doc.body);
        if (blocks.length === 0) return;
        const index = blockIndexForLine(blocks, lineNo);
        const target = container.querySelector<HTMLElement>(
          `[data-block-index="${index}"]`,
        );
        if (!target) return;
        target.scrollIntoView({ block: "start" });
        target.setAttribute("data-anchored", "");
        target.classList.add("border-l-2", "border-bright");
        anchorTimer = setTimeout(() => {
          target.removeAttribute("data-anchored");
          target.classList.remove("border-l-2", "border-bright");
        }, ANCHOR_MS);
      } catch {
        // An anchor miss must never break the render.
      }
    });
  });

  return (
    <div class="flex h-full min-h-0 flex-col">
      <Show when={props.editable}>
        <div class="flex items-center justify-end gap-2 border-b border-line px-3 py-2">
          <Show
            when={editing()}
            fallback={
              <Button
                variant="ghost"
                size="sm"
                leading="edit"
                onClick={startEdit}
              >
                EDIT
              </Button>
            }
          >
            <Button
              variant="ghost"
              size="sm"
              onClick={cancel}
              disabled={saving()}
            >
              CANCEL
            </Button>
            <Button
              variant="primary"
              size="sm"
              leading="check"
              onClick={() => void save()}
              disabled={saving()}
            >
              SAVE
            </Button>
          </Show>
        </div>
      </Show>
      <div
        ref={(el) => {
          scrollRef = el;
          rememberScroll(el, () => `${itemKey()}-read`);
        }}
        class="min-h-0 flex-1 overflow-auto p-3"
        style={{ "font-size": `${fontStepMetrics(props.fontStep).size}px` }}
      >
        <Show
          when={editing()}
          fallback={<Markdown streamStable>{props.document.body}</Markdown>}
        >
          <Textarea
            rows={24}
            aria-label="Edit document body"
            value={draft()}
            onInput={(e) => setDraft(e.currentTarget.value)}
          />
        </Show>
      </div>
    </div>
  );
}
